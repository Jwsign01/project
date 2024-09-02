# -*- coding: utf-8 -*-
"""jwsign0.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1cJ89PcQI7VPNNSyV0rXVhAoo0t8bGdIW
"""

import pandas as pd
import zipfile
import torch
from torch.utils.data import Dataset, DataLoader, random_split
import torch.nn as nn
import os
from os import walk
from torch.nn.utils.rnn import pad_sequence
import torch.nn.functional as F
from sklearn.model_selection import ParameterGrid
import matplotlib.pyplot as plt
from captum.attr import IntegratedGradients
import numpy as np

!pip3 install captum

import warnings

# Ignore all warnings
warnings.filterwarnings('ignore')

!pip3 install ax-platform
from ax.service.ax_client import AxClient, ObjectiveProperties
from ax.service.utils.report_utils import exp_to_df
from ax.utils.notebook.plotting import init_notebook_plotting, render
from ax.utils.tutorials.cnn_utils import evaluate, load_mnist, train
init_notebook_plotting(offline=True)

import plotly.io as pio
pio.renderers.default = "colab"

import torch
torch.cuda.is_available()

#set a pathroot so it can be changed if file moves
pathroot = 'D:/dl/assignment/'

#read the dataset
class ProteinDataset(Dataset):
    def __init__(self, zip_file_path, labels_csv_path=None):
        #set file path
        self.zip_file_path = zip_file_path

        #test if label information will be inputed
        self.labels_available = labels_csv_path is not None

        #if there is label inputed, then it should be train dataset
        if self.labels_available:
            for root, dirs, files in os.walk(self.zip_file_path):
              self.protein_ids = [file_name.replace('_train.csv', '') for file_name in files]
            self.labels_df = pd.read_csv(labels_csv_path)
            self.labels_df.set_index('PDB_ID', inplace=True)
        #if no label inputed, then it should be test dataset
        else:
            for root, dirs, files in os.walk(self.zip_file_path):
                self.protein_ids = [file_name.replace('_test.csv', '') for file_name in files]

        #write a dictionary to assign numerical values to secondary structures,starting from 0
        self.acid_seq = "ACDEFGHIKLMNPQRSTVWY"
        self.acid_dict = dict(zip(list(self.acid_seq),list(range(20))))

    def __len__(self):
        return len(self.protein_ids)

    def __getitem__(self, idx):
        protein_id = self.protein_ids[idx]

        #if there is label inputed, then it should be train dataset
        if self.labels_available:
            df = pd.read_csv(pathroot + 'train/' + str(protein_id) + '_train.csv')

        #if no label inputed, then it should be test dataset
        else:
            df = pd.read_csv(pathroot + 'test/' + str(protein_id) + '_test.csv')
        # Extract amino acid sequence and convert to indices
        amino_acids = df['AMINO_ACID'].tolist()
        amino_acid_indices = [self.acid_dict.get(aaname) for aaname in amino_acids]
        sequence_tensor = torch.tensor(amino_acid_indices, dtype=torch.long)

          # Extract PSSM scores
        pssm = df.iloc[:, 2:].values  # Assuming PSSM scores start from the 3rd column
        pssm_tensor = torch.tensor(pssm, dtype=torch.float32)

        #if there is label, it should be a train dataset so return sequence tensor, pssm tensor and label tensor
        if self.labels_available:
          # extract label
            label_dict = {'C': 0, 'E': 1, 'H': 2}
            sec_struct = self.labels_df.loc[protein_id, 'SEC_STRUCT']
            label_indices=[label_dict.get(st) for st in sec_struct]
            label_tensor = torch.tensor(label_indices, dtype=torch.long)
            return sequence_tensor, pssm_tensor, label_tensor
        #if no label then only return sequence tensor and pssm tensor
        else:
            return sequence_tensor, pssm_tensor

#used to pad train dataset for 3 tensors, since proteins have different number of residues
def collate_fn(batch):
    sequences, pssms, labels = zip(*batch)
    padded_sequences = pad_sequence(sequences, batch_first=True, padding_value=0)
    padded_pssms = pad_sequence(pssms, batch_first=True, padding_value=0)
    padded_labels = pad_sequence(labels, batch_first=True, padding_value=0)

    return padded_sequences, padded_pssms, padded_labels
#used to pad test dataset because it does not contain label tensor
def collate_fn2(batch):
    sequences, pssms= zip(*batch)
    padded_sequences = pad_sequence(sequences, batch_first=True, padding_value=0)
    padded_pssms = pad_sequence(pssms, batch_first=True, padding_value=0)
    return padded_sequences, padded_pssms

# read train dataset and split them
train = ProteinDataset(pathroot + 'train' , pathroot + 'labels_train.csv')
dataset_size = len(train)
#70% of the train dataset are used to train, and the rest 30% are used to validate
train_size = int(dataset_size * 0.7)
validation_size = dataset_size - train_size
train_dataset, validation_dataset = random_split(train, [train_size, validation_size])

#this is the net
class ProteinCNN(nn.Module):
    def __init__(self, input_channels,output_channels, num_classes,dropout_rate):
        super(ProteinCNN, self).__init__()
        self.conv1 = nn.Conv1d(input_channels, output_channels, kernel_size=5, padding=2)

        self.conv2 = nn.Conv1d(64, 128, kernel_size=5, padding=2)

        self.conv3 = nn.Conv1d(128, 256, kernel_size=5, padding=2)

        #self.conv4 = nn.Conv1d(256, 512, kernel_size=5, padding=2)
        self.final_conv = nn.Conv1d(256, num_classes, kernel_size=1)
        self.relu = nn.ReLU()
        #add dropout to prevent overfitting
        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, x):

        x = self.conv1(x)

        x = self.relu(x)
        x = self.dropout(x)
        x = self.relu(self.conv2(x))

        x = self.dropout(x)
        x = self.relu(self.conv3(x))
        x = self.dropout(x)
        #x = self.relu(self.conv4(x))
        x = self.final_conv(x)

        return x

#run the model on the test set and get the predictions in a list and test loss, where the list contain lists that represent each protein, and within
#each protein list, there are numbers that represent the structures as numerical values
def val_pred(model,data_loader,loss_fn):
    model.eval()  # Set the model to evaluation mode
    predictions = []
    total_samples = 0
    total_loss = 0.0
    dataset = data_loader
    with torch.no_grad():

        for sequences, pssms, labels in dataset:
            sequences = sequences.long()

            pssms = pssms.float()

            # Forward pass to get outputs
            #join the sequence and pssm tensors,since sequence tensor has one less dimension,
            #will need to add a dimension at index 2 to sequence tensor
            output = torch.cat((sequences.unsqueeze(2), pssms), dim = 2)

            #exchange the dimension at index 2 (1 column from sequence,20 columns from pssm)
            #and dimension at index 1 (number of residues) to make sure
            #the input channel is 21

            output = output.permute(0,2,1)
            outputs = model(output)
            loss = loss_fn(outputs, labels)
            total_loss += loss.item()
            # Convert outputs to predicted class indices
            _, predicted = torch.max(outputs, 1)

            predictions.extend(predicted.cpu().numpy())
            total_samples += output.size(0)
        #calculate loss
        average_test_loss = total_loss / len(data_loader)
        print('loss' + ':' + str(average_test_loss))
    #return predictions as a list and average test loss
    return predictions, average_test_loss

#test the accuracy of predictions
def test_accuracy(dataset,predictions):
    true_labels = []
    #get true data from the dataset, stored in a list named true_list
    for seq, pssms, labels in dataset:
        protein_label = []
        for label in labels:
            labels = int(label)
            protein_label.append(label)
        true_labels.append(protein_label)


    accuracy = 0
    total_predictions = 0
    #iterate over the prediction list obtained
    for i in range(len(predictions)):
        #iterate over each protein list that stored the structure data
        pred = predictions[i]

        true = true_labels[i]
        #since I did padding, true data will be shorter, so truncate the padding part
        if len(pred) != len(true):
            pred = pred[0:len(true)]

        # if the structure for the residue is the same as the one in the true list, add one to accuracy
        for idx in range(len(true)):
            if pred[idx] == true[idx]:
                accuracy += 1
            total_predictions += 1

    # Calculate the accuracy percentage
    accuracy_percentage = (accuracy / total_predictions) * 100
    return accuracy_percentage
    #print(f'Accuracy: {accuracy_percentage:.2f}%')

#create dictionaries to store the losses and accuracy for plotting later, where the key will be the trial index, each trial contains a list
# of all epochs' losses or accuracies
train_losses, val_losses, val_accuracies = {}, {}, {}

def train_loop(model, data_loader,test, test_loader, optimizer, lossfn, num_ep, patience, trial_index):

    global train_losses, val_losses, val_accuracies
    num_epochs = num_ep
    best_test_accuracy = 0
    #best_model_state = None
    epochs_no_improve = 0
    train_loss_list = []
    test_loss_list = []
    val_acc_list = []

    for epoch in range(num_epochs):
        model.train()
        running_loss = 0.0
        i = 0
        accuracy = 0

        for inputs, pssm_profiles, labels in data_loader:
            optimizer.zero_grad()
            #add a dimension to inputs so it can be joined with pssm tensor


            inp = inputs.unsqueeze(2)
            #join two tensors to get input
            x = torch.cat((inp, pssm_profiles),dim = 2)
            #exchange the values on dimension 1 and 2, since input channel equals 21,
            #which is 1 input channel of sequence + 20 input channels of pssm profiles
            x = x.permute(0, 2, 1)

            outputs = model(x.float())
            loss = lossfn(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            #report every 100 batches
            i += 1
            if i%100 == 0:
              print(f"now batch {i}")
        avg_train_loss = running_loss / len(data_loader)


        #calculate the loss and accuracy on validation set
        predictions1, avg_test_loss = val_pred(model,test_loader,lossfn)
        accuracy = test_accuracy(test,predictions1)
        print(f'Epoch {epoch+1}/{num_epochs}, Training Loss: {avg_train_loss:.4f}, Test Loss: {avg_test_loss:.4f},Accuracy : {accuracy:.4f}%')

        #add the train loss, validation loss and validation accuracy to the list for each epoch
        train_loss_list.append(avg_train_loss)
        test_loss_list.append(avg_test_loss)
        val_acc_list.append(accuracy)

        # Check if this is the best model (based on accuracy)
        if accuracy > best_test_accuracy:
            best_test_accuracy = accuracy
            #best_model_state = model.state_dict().copy()
            epochs_no_improve = 0
        #if not improving more than number of patience then stop early
        else:
            epochs_no_improve +=1
            if epochs_no_improve >= patience:
                print(f"Early stopping triggered at epoch {epoch+1}")
                break

    train_losses[trial_index] = train_loss_list
    val_losses[trial_index] = test_loss_list
    val_accuracies[trial_index] = val_acc_list

    print('Finished Training')
    # Return the best test loss, accuracy and the  model
    return avg_test_loss, accuracy, model

ax_client = AxClient()

from ax import optimize

def train_evaluate(parameterization, train_dataset, validation_dataset, num_ep, patience, trial_index):

    # Here, parameterization is a dict with hyperparameters
    #set the hyperparameters
    dropout_rate=parameterization["dropout_rate"]
    model = ProteinCNN(input_channels=21, output_channels=64, num_classes=3,dropout_rate =dropout_rate )
    lr=parameterization["lr"]
    optimizer = torch.optim.Adam(model.parameters(), lr)
    loss_fn = torch.nn.CrossEntropyLoss()
    batch_size = parameterization["batch_size"]
    print(f"Now running with dropout rate: {dropout_rate}, lr:{lr}, batch size:{batch_size})")

    #load the train dataset and validation dataset
    train_loader = DataLoader(train_dataset, batch_size , shuffle=True, num_workers=0, collate_fn=collate_fn)
    validation_loader = DataLoader(validation_dataset, batch_size, shuffle=False, num_workers=0, collate_fn=collate_fn)

    #get test loss, accuracy and trained model
    avg_test_loss, accuracy, trained_model = train_loop(model, train_loader,validation_dataset, validation_loader, optimizer, loss_fn, num_ep, patience, trial_index) # Assume this is computed during your training loop
    return {"loss": (avg_test_loss, 0.0),"accuracy":(accuracy,0.0)}

def plot_metrics(metrics_dict, title, ylabel, xlabel='Epoch'):
    plt.figure(figsize=(10, 6))

    for trial_index, metrics in metrics_dict.items():
        plt.plot(metrics, label=f'Trial {trial_index}')

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.legend()
    plt.grid(True)
    plt.show()

# Create an experiment with required arguments: name, parameters, and objective_name.
ax_client.create_experiment(
    name="tune_cnn_on_mnist",  # The name of the experiment.
    parameters=[
        {
            "name": "lr",
            "type": "range",
            "bounds": [0.0005, 0.001],

            "value_type": "float",
            "log_scale": True,

        },
        {
            "name": "dropout_rate",
            "type": "range",
            "bounds": [0.0, 0.5],
        },
        {
            "name":"batch_size",
            "type":"choice",
            "values": [16,32],
        },
    ],
    objectives={"accuracy": ObjectiveProperties(minimize=False)},
)

# Attach the trial
ax_client.attach_trial(
    parameters={"lr": 0.001, "dropout_rate": 0.00, "batch_size":16}
)

# Get the parameters and run the trial
baseline_parameters = ax_client.get_trial_parameters(trial_index=0)

ax_client.complete_trial(trial_index=0, raw_data=train_evaluate(baseline_parameters,train_dataset,validation_dataset,num_ep=15, patience = 3, trial_index = 0))
num_ep = 15
for i in range(7):
    parameters, trial_index = ax_client.get_next_trial()
    ax_client.complete_trial(trial_index=trial_index, raw_data=train_evaluate(parameters,train_dataset,validation_dataset,num_ep = num_ep, patience = 3, trial_index = trial_index))

# Plot training loss for each trial
plot_metrics(train_losses, 'Training Loss by Trial', 'Loss')

# Plot validation loss for each trial
plot_metrics(val_losses, 'Validation Loss by Trial', 'Loss')

# Plot validation accuracy for each trial
plot_metrics(val_accuracies, 'Validation Accuracy by Trial', 'Accuracy')

#get the best parameters and display
best_parameters, values = ax_client.get_best_parameters()
best_parameters

#plot
render(ax_client.get_contour_plot(param_x="lr", param_y="dropout_rate",  metric_name="accuracy"))
render(
    ax_client.get_optimization_trace()
)

#get best set of parameters
df = ax_client.get_trials_data_frame()
best_arm_idx = df.trial_index[df["accuracy"] == df["accuracy"].max()].values[0]
best_arm = ax_client.get_trial_parameters(best_arm_idx)
best_arm
#use the best set of parameters to train on the train dataset and get the trained model
loss_fn = torch.nn.CrossEntropyLoss()
dropout_rate=best_arm['dropout_rate']
model_best = ProteinCNN(
        input_channels=21,
        output_channels=64,
        num_classes=3,
        dropout_rate=dropout_rate
    )
batch_size = best_arm['batch_size']
optimizer = torch.optim.Adam(model_best.parameters(), lr=best_arm['lr'])
#load the train dataset and validation dataset
train_loader = DataLoader(train_dataset, batch_size, shuffle=True, num_workers=0, collate_fn=collate_fn)
validation_loader = DataLoader(validation_dataset, batch_size, shuffle=False, num_workers=0, collate_fn=collate_fn)
#run the model
loss,acc,trained_model = train_loop(model_best, train_loader,validation_dataset, validation_loader, optimizer, loss_fn, num_ep = num_ep , patience =3,trial_index= 1)

#check the importance of features
#create integratedGradients object
#trained_model.eval()

ig = IntegratedGradients(trained_model)
#get the input tensor
for inputs, pssm_profiles, labels in validation_loader:
    # Prepare the input tensor as done before

    inp = inputs.unsqueeze(2)

    #join two tensors to get input
    x = torch.cat((inp, pssm_profiles),dim = 2)
    #exchange the values on dimension 1 and 2, since input channel equals 21,
    #which is 1 input channel of sequence + 20 input channels of pssm profiles
    x = x.permute(0, 2, 1)
    #since ig.attribute cannot accept multiple output to calculate gradient, have to only keep the first one residue
    x= x[:,:,:1]
    test_input_tensor = x
    #get the feature names, consists of sequence name and pssm feature names
    sequence_feature_names = [f'Pos{i}' for i in range(inputs.shape[1])]
    pssm_feature_names = [f'PSSM{i}' for i in range(pssm_profiles.shape[1])]
    #only check one protein
    break

#conbine the two feature names
feature_names = sequence_feature_names + pssm_feature_names

#set
test_input_tensor.requires_grad_()
#get attributions of all 3 structures
index_to_structure = {0:'C', 1:'E', 2:'H'}
attributions = {}
for index, structure in index_to_structure.items():
    attr= ig.attribute(test_input_tensor, target = index, return_convergence_delta=False)
    attributions[structure] = attr


def visualize_importances(class_name, attributions, feature_names):
    plt.figure(figsize=(12, 4))
    attr = attributions[class_name].detach().numpy()

    # Sum the attributions across the input features for each sequence position
    summed_attr = attr.sum(axis=0)  # Sum along the batch dimension

    plt.plot(summed_attr, label=f'Importance for {class_name}')
    plt.ylabel('Importance')
    plt.xlabel('Amino acid name')
    plt.legend()
    plt.title(f'Feature importances for predicting {class_name}')
    plt.show()



# Visualize for each secondary structure type
for index, structure in index_to_structure.items():
    visualize_importances(structure, attributions, feature_names)

#Do another prediction and calculate the accuracy on the whole trainset
trained_model.eval()

whole_train = DataLoader(train, batch_size, shuffle=False, num_workers=0, collate_fn=collate_fn)

predictions1,test_loss = val_pred(trained_model,whole_train,loss_fn)
test_accuracy(train,predictions1)

#put test dataset into the model and get the predictions as a list(still in numerical form)
def evaluation(model, data_loader):
    model.eval()  # Set the model to evaluation mode
    predictions = []

    dataset = data_loader
    with torch.no_grad():
        for sequences, pssms in dataset:

            sequences = sequences.long()
            pssms = pssms.float()
            #same, join sequence tensor and pssm tensor, then exchange the dimensions
            output = torch.cat((sequences.unsqueeze(2), pssms), dim = 2)
            output = output.permute(0,2,1)
            outputs = model(output)

            # Convert outputs to predicted class indices
            _, predicted = torch.max(outputs, 1)

            predictions.extend(predicted.cpu().numpy())

    #return predictions stored in a list
    return predictions

#convert numerical values to categorical values for test dataset, returns a list of predictions of proteins with
#secondary structrues as characters
def create_pred(data_loader, predictions):
    #first get the name of proteins stored in a list
    list_seq = []
    for seq,  pssms in test:
        protein_seq = []
        for s in seq:
            s = int(s)
            protein_seq.append(s)
        list_seq.append(protein_seq)

    #match predictions with the protein names
    for i in range(len(predictions)):

        pred = predictions[i]

        sequence = list_seq[i]
        #since we have done padding , we will adjust the length of prediction to the origial number of residues,
        #which means to cut the padded part
        if len(pred) != len(sequence):
            pred = pred[0:len(sequence)]
        predictions[i] = pred
    #convert the numerical representation back to secondary structure
    index_to_structure = {0:'C', 1:'E', 2:'H'}
    structure_predictions = [[index_to_structure[pred] for pred in protein_preds] for protein_preds in predictions]

    return structure_predictions

#read the test file
test = ProteinDataset(pathroot + 'test')
test_loader = DataLoader(test,batch_size, shuffle=False, num_workers=0, collate_fn=collate_fn2)

#create predictions for the test dataset
predictions = evaluation(trained_model,test_loader)
#convert the numerical values into categorical values
sturct_pred = create_pred(test, predictions)

#write csv file to export
import csv
import os
#make a dictionary to make sure the residue of proteins correspond to the correct value
pred_dict = {}
for root, dirs, files in os.walk(pathroot + 'test'):
    protein_id = [file_name.replace('_test.csv', '') for file_name in files]
for index, pred in enumerate(sturct_pred):
    for i in range(len(sturct_pred[index])):
            residue_name = protein_id[index] + '_' + str(i+1)
            structure = pred[i]
            pred_dict.update({residue_name : structure})
#get the sequences in the required order from the file
sequence_values = {}
with open(pathroot + 'seqs_test.csv', mode='r') as seq_file:
    seq_reader = csv.reader(seq_file)
    next(seq_reader, None)
    for row in seq_reader:
        sequence_values.update({row[0] : row[1]})


#write the file
with open('protein_structure_predictions.csv', mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(['ID', 'Structure'])  # Adjust as needed
    for name in sequence_values:

        seq = sequence_values[name]
        for i in range(len(seq)):
            residue_name = name + '_' + str(i+1)
            pred_st = pred_dict[residue_name]
            writer.writerow([residue_name, ''.join(pred_st)])
