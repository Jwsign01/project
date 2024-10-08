# -*- coding: utf-8 -*-
"""Xi_Wu_Pre8.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1Rpope8Ke5030Hk6FFSj7C906RvOOfhkA
"""

import pandas as pd
import statsmodels.api as sm
import numpy as np
from scipy.stats import ks_2samp, chi2_contingency, norm
from scipy import stats
import matplotlib.pyplot as plt
import warnings
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import cross_val_score
warnings.filterwarnings('ignore', category=pd.errors.SettingWithCopyWarning)

from google.colab import drive
drive.mount('/content/drive')

np.random.seed(42)

mutual_fund_path = '/content/drive/MyDrive/mutualall_data.xlsx'
hedge_fund_path = '/content/drive/MyDrive/hedgeall_data.xlsx'
factor_path = '/content/drive/MyDrive/factor_data.csv'
df_hedge = pd.read_excel(hedge_fund_path, header=0)
df_mutual = pd.read_excel(mutual_fund_path, header=0)
hedge_fund_df = df_hedge.dropna(subset = ['Date'])
mutual_fund_df = df_mutual.dropna(subset = ['Date'])
factor_df = pd.read_csv(factor_path, header=0)



na_counts = factor_df.isna().sum()

print("number of missing values：")
print(na_counts)

# check missing values
columns_with_na = na_counts[na_counts > 0]
if not columns_with_na.empty:
    print("\ncolumns with missing values and number of missing values：")
    print(columns_with_na)
else:
    print("\nNo missing value.")

def process_fund_data(fund_df, factor_df, start_date, end_date, min_months):
    """
    Process fund data, filter data from the past 20 years, group by fund code, and calculate the Alpha value.

    Parameters:
    - fund_df: fund return dataframe
    - factor_df: six-factor dataframe
    - start_date: Start date
    - end_date: End date
    - min_months: Minimum number of months of data required to keep a fund

    Returns:
    - merged_df: Merged DataFrame of factors and fund returns
    """

    # convert the 'Date' column in both DataFrames to datetime format
    fund_df.loc[:, 'Date'] = pd.to_datetime(fund_df['Date'])
    factor_df.loc[:, 'Date'] = pd.to_datetime(factor_df['dateff'])

    # filter out data from the past 20 years
    fund_yr = (fund_df['Date'] >= start_date) & (fund_df['Date'] <= end_date)
    fund_df = fund_df.loc[fund_yr]
    factor_yr = (factor_df['Date'] >= start_date) & (factor_df['Date'] <= end_date)
    factor_df = factor_df.loc[factor_yr]

    # merge the factor data and return data
    fund_df.loc[:, 'YearMonth'] = fund_df['Date'].dt.to_period('M')
    factor_df.loc[:, 'YearMonth'] = factor_df['Date'].dt.to_period('M')
    merged_df = pd.merge(fund_df, factor_df, on='YearMonth', suffixes=('_fund', '_factor'))

    # sort by date
    merged_df = merged_df.sort_values(by=['Fund_ID', 'Date_fund']).reset_index(drop=True)

    return merged_df

def calculate_alpha(df):
    """
    Calculate Alpha for each fund

    Parameter：
    - df: Dataframe containing fund returns and factors

    Returns：
    - alpha: Alpha of each fund
    """
    # make sure the returns are not object
    rolling_performance = df.loc[:,'Rolling_Performance'].copy()
    if rolling_performance.dtype == 'object':
        df['Rolling_Performance'] = pd.to_numeric(rolling_performance, errors='coerce')
    if df['Rolling_Performance'].dtype == 'object':
        print("still object")

    # get dependent variable, which is the difference between return and risk free return

    y = df['Rolling_Performance'] - df['rf']

    # get independent variables
    X = df[['mktrf', 'smb', 'hml', 'rmw', 'cma']]


    # add a constant
    X = sm.add_constant(X)
#     y = y.apply(pd.to_numeric, errors='coerce')
    if X.isnull().values.any() or y.isnull().values.any():
        print("Missing values found in the following columns:")
        print(X.isnull().sum())
        print("Dependent variable (y) missing values:", y.isnull().sum())


    if np.isinf(X).values.any() or np.isinf(y).values.any():
        print("Infinite values found in the following columns:")
        print(np.isinf(X).sum())
        print("Dependent variable (y) infinite values:", np.isinf(y).sum())

    # run regression
    model = sm.OLS(y, X).fit()

    # get Alpha
    alpha = model.params['const']

    return alpha
def calculate_alpha_for_intervals(filtered_df, interval_months):
    """
    Calculate Alpha based on given time interval

    Parameters：
    - filtered_df:  merged df during given time period
    - interval_months: time interval, 3 or 6 or 12

    Returns：
    - interval_alpha_df: Alpha for each time interval（DataFrame）
    """
    interval_alpha_df = pd.DataFrame(columns=['Fund_ID', 'Interval', 'Alpha'])

    # group by fund id
    grouped = filtered_df.groupby('Fund_ID')

    for fund_id, group in grouped:
        group = group.sort_values('Date_fund')

        # group by time interval
        for i in range(0, len(group), interval_months):
            interval_df = group.iloc[i:i + interval_months]

            # make sure there are enough data
            if len(interval_df) == interval_months:
                alpha = calculate_alpha(interval_df)
                new_row = pd.DataFrame({'Fund_ID': [fund_id], 'Interval': [i // interval_months], 'Alpha': [alpha]})
                interval_alpha_df = pd.concat([interval_alpha_df, new_row], ignore_index=True)


    return interval_alpha_df

def construct_contingency_table(alpha_df):
    """
    Construct a contingency table from Alpha data

    Parameters:
    alpha_df (DataFrame): dataFrame containing alpha values with 'Interval', 'Fund_ID', and 'Alpha' columns

    Returns:
    contingency_table (DataFrame): DataFrame representing the contingency table, contains WW, LL, WL, and LW
    """
    contingency_table = pd.DataFrame(0, index=alpha_df['Interval'].unique(), columns=['WW', 'LL', 'WL', 'LW'])

    # group by interval
    intervals = alpha_df['Interval'].unique()
    intervals.sort()

    for i in range(len(intervals) - 1):
        interval_1 = intervals[i]
        interval_2 = intervals[i + 1]

        alpha_1 = alpha_df[alpha_df['Interval'] == interval_1]
        alpha_2 = alpha_df[alpha_df['Interval'] == interval_2]
        # get median in the current interval
        alpha_1_median = alpha_1['Alpha'].median()
        alpha_2_median = alpha_2['Alpha'].median()
        # get Alpha of each fund in the current interval
        for fund_id in alpha_df['Fund_ID'].unique():
            alpha_1_fund = alpha_1[alpha_1['Fund_ID'] == fund_id]['Alpha'].values
            alpha_2_fund = alpha_2[alpha_2['Fund_ID'] == fund_id]['Alpha'].values

            if len(alpha_1_fund) > 0 and len(alpha_2_fund) > 0:
                alpha_1_value = alpha_1_fund[0]
                alpha_2_value = alpha_2_fund[0]
                # compare the Alpha of each fund to the median and add WW or WL or LL or LW to
                # the contingency table
                if alpha_1_value > alpha_1_median and alpha_2_value > alpha_2_median:
                    contingency_table.loc[interval_1, 'WW'] += 1
                elif alpha_1_value <= alpha_1_median and alpha_2_value <= alpha_2_median:
                    contingency_table.loc[interval_1, 'LL'] += 1
                elif alpha_1_value > alpha_1_median and alpha_2_value <= alpha_2_median:
                    contingency_table.loc[interval_1, 'WL'] += 1
                else:
                    contingency_table.loc[interval_1, 'LW'] += 1

    return contingency_table

def calculate_cpr_z_chisq(contingency_table):
    """
    Calculate CPR, Z statistic, and Chi-square from the contingency table

    Parameters:
    contingency_table (DataFrame): DataFrame representing the contingency table

    Returns:
    cpr (float): Calculated CPR value
    z (float): Calculated Z statistic
    chi_square (float): Calculated Chi-square value
    """
    # Calculate the expected frequencies
    WW = contingency_table['WW'].sum()
    LL = contingency_table['LL'].sum()
    WL = contingency_table['WL'].sum()
    LW = contingency_table['LW'].sum()

    # Calculate CPR
    cpr = (WW * LL) / (WL * LW)

    # Calculate Z statistic
    ln_cpr = np.log(cpr)
    sd = np.sqrt((1/WW) + (1/LL) + (1/WL) + (1/LW))
    z = ln_cpr / sd

    # Calculate Chi-square
    N = WW + LL + WL + LW

    D1 = (WW + WL) * (WW + LW) / N
    D2 = (WL + LL) * (WW + WL) / N
    D3 = (LW + LL) * (WW + LW) / N
    D4 = (LW + LL) * (WL + LL) / N

    chi_square = ((WW - D1) ** 2 / D1) + ((WL - D2) ** 2 / D2) + ((LW - D3) ** 2 / D3) + ((LL - D4) ** 2 / D4)

    return cpr, z, chi_square

def calculate_wins_loses(alpha_df):
    """
    Compare the Alpha of each fund to the median on multiple intervals, if larger than the median
    then labeled as "1" in Wins, otherwise "0". If smaller than the median then labeled as "1" in Loses,
    otherwise "0".

    Parameters:
    alpha_df (DataFrame): dataFrame containing alpha values with 'Interval', 'Fund_ID', and 'Alpha' columns

    Returns:
    result_df (DataFrame): DataFrame with wins and loses
    """
    interval_list = alpha_df['Interval'].unique()
    result_df = pd.DataFrame()
    for interval in interval_list:
        interval_df = alpha_df[alpha_df['Interval'] == interval]
        median_alpha = interval_df['Alpha'].median()
        interval_df['Wins'] = (interval_df['Alpha'] > median_alpha).astype(int)
        interval_df['Loses'] = (interval_df['Alpha'] <= median_alpha).astype(int)
        result_df = pd.concat([result_df, interval_df])
    return result_df

def ks_test(win_lose_df, theoretical_dist, num_simulations=1000):
    """
    Perform KS test and Monte Carlo significance test.

    Parameters:
    win_lose_df (DataFrame): DataFrame with wins and loses
    theoretical_dist (str): Type of theoretical distribution, 'binomial' or 'normal'
    num_simulations (int): Number of simulations for Monte Carlo significance test

    Returns:
    ks_stat_wins (float): KS statistic for wins
    p_value_wins (float): P-value for wins
    ks_stat_loses (float): KS statistic for loses
    p_value_loses (float): P-value for loses
    """
    wins = win_lose_df['Wins'].values
    loses = win_lose_df['Loses'].values

    if theoretical_dist == 'binomial':
        theoretical_wins = np.random.binomial(n=1, p=0.5, size=len(wins))
        theoretical_loses = np.random.binomial(n=1, p=0.5, size=len(loses))
    elif theoretical_dist == 'normal':
        theoretical_wins = norm.rvs(loc=np.mean(wins), scale=np.std(wins), size=len(wins))
        theoretical_loses = norm.rvs(loc=np.mean(loses), scale=np.std(loses), size=len(loses))
    # Perform k-s test
    ks_stat_wins, p_value_wins = ks_2samp(wins, theoretical_wins)
    ks_stat_loses, p_value_loses = ks_2samp(loses, theoretical_loses)
    # Perform Monte Carlo significance test
    if theoretical_dist == 'normal':
        mc_sig_wins = monte_carlo_significance(wins, theoretical_wins, num_simulations)
        mc_sig_loses = monte_carlo_significance(loses, theoretical_loses, num_simulations)
        return ks_stat_wins, p_value_wins, ks_stat_loses, p_value_loses, mc_sig_wins, mc_sig_loses
    else:
        return ks_stat_wins, p_value_wins, ks_stat_loses, p_value_loses

def monte_carlo_significance(sample, theoretical_sample, num_simulations=1000):
    """
    Perform Monte Carlo significance test.

    Parameters:
    sample: Sample data
    theoretical_sample: Theoretical sample data
    num_simulations: Number of simulations

    Returns:
    p_value (float): P-value
    """
    # Initialize an empty list to store KS statistics from each simulation
    ks_stats = []
    for i in range(num_simulations):
        # Generate a simulated sample by randomly sampling from the theoretical distribution
        simulated_sample = np.random.choice(theoretical_sample, size=len(sample), replace=True)
        # Compute the KS statistic for the observed sample versus the simulated sample.
        ks_stat, p_val = ks_2samp(sample, simulated_sample)
        ks_stats.append(ks_stat)
    ks_stats = np.array(ks_stats)
    # Calculate the observed KS statistic for the observed sample versus the theoretical sample.
    observed_ks_stat, p_values = ks_2samp(sample, theoretical_sample)

    # Calculate the p-value as the proportion of KS statistics from simulations that are
    # greater than or equal to the observed KS statistic.
    p_value = np.mean(ks_stats >= observed_ks_stat)
    return p_value

def generate_binomial_table(hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                            mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                            hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                            mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf):
    """
    Generate a summary table for binomial distribution k-s test results

    Parameters:
    alpha_df (DataFrame): dataFrame containing alpha values with 'Interval', 'Fund_ID', and 'Alpha' columns

    Returns:
    result_df (DataFrame): DataFrame with binomial distribution k-s test results
    """
    intervals = ['3m', '6m', '12m']
    results = []
    # For hedge fund and mutual fund across 3 intervals, calculate wins loses and perform k-s tests
    for alpha_df, interval in zip([hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                                   mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                                   hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                                   mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf], intervals * 4):
        win_lose_df = calculate_wins_loses(alpha_df)
        # Perform ks test
        ks_stat_wins, p_value_wins, ks_stat_loses, p_value_loses = ks_test(win_lose_df, 'binomial')
        fund_type = 'Hedge Fund' if 'hedge' in alpha_df.columns[0] else 'Mutual Fund'
        alpha_type = 'RF' if 'rf' in alpha_df.columns[0] else 'Normal'
        results.append([interval, fund_type, alpha_type, ks_stat_wins, p_value_wins, ks_stat_loses, p_value_loses])

    result_df = pd.DataFrame(results, columns=['Interval', 'Fund_Type', 'Alpha_Type', 'Wins_KS_Stat', 'Wins_P_Value',
                                               'Loses_KS_Stat', 'Loses_P_Value'])
    return result_df

def generate_normal_table(hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                          mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                          hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                          mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf):
    """
    Generate a summary table for normal distribution k-s test results

    Parameters:
    alpha_df (DataFrame): dataFrame containing alpha values with 'Interval', 'Fund_ID', and 'Alpha' columns

    Returns:
    result_df (DataFrame): DataFrame with normal distribution k-s test results
    """
    intervals = ['3m', '6m', '12m']
    results = []

    for alpha_df, interval in zip([hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                                   mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                                   hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                                   mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf], intervals * 4):
        win_lose_df = calculate_wins_loses(alpha_df)
        # Perform ks test
        ks_stat_wins, asy_sig_wins, ks_stat_loses, asy_sig_loses, mc_sig_wins, mc_sig_loses = ks_test(win_lose_df, 'normal')
        fund_type = 'Hedge Fund' if 'hedge_' in alpha_df.columns[0] else 'Mutual Fund'
        alpha_type = 'RF' if '_rf' in alpha_df.columns[0] else 'Normal'

        results.append([interval, fund_type, alpha_type, ks_stat_wins, asy_sig_wins, mc_sig_wins,
                        ks_stat_loses, asy_sig_loses, mc_sig_loses])

    result_df = pd.DataFrame(results, columns=['Interval', 'Fund_Type', 'Alpha_Type', 'Wins_KS_Stat', 'Asy_Sig_Wins',
                                               'MC_Sig_Wins', 'Loses_KS_Stat', 'Asy_Sig_Loses', 'MC_Sig_Loses'])
    return result_df

def train_and_predict(filtered_df, train_start, start_date, end_date):
    """
    Use expand rolling window and random forest to train and predict. Train dataset will start from the train_start date and end
    at start_date which is for prediction initially, after one interval is predicted, the actual value of it will be added to the
    training dataset for later training.

    Parameters:
    - filtered_df: merged df during given time period
    - train_start: start date of training (YYYY-MM)
    - start_date: start date of prediction (YYYY-MM)
    - end_date: end date of prediction (YYYY-MM)

    Returns:
    - results_df: DataFrame which contains actual values, prediction values, fund id and date
    - feature_importances_df: DataFrame with feature importance
    """
    results = []
    feature_importances = []
    mse_values = []

    # Sort by date
    filtered_df['Date_fund'] = pd.to_datetime(filtered_df['Date_fund'])
    filtered_df = filtered_df.sort_values('Date_fund').reset_index(drop=True)
    train_start = pd.to_datetime(train_start)
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    current_date = start_date

    # Start
    while current_date <= end_date:
        # Get training dataset and test dataset
        train_df = filtered_df[(filtered_df['Date_fund'] >= train_start) & (filtered_df['Date_fund'] < current_date)]
        test_df = filtered_df[(filtered_df['Date_fund'] >= current_date) & (filtered_df['Date_fund'] < current_date + pd.DateOffset(months=12))]

        # Make sure there is data in the given interval
        if len(train_df) < 1 or len(test_df) < 1:
            current_date += pd.DateOffset(months=12)
            continue

        # Check if rolling performance is object
        if train_df['Rolling_Performance'].dtype == 'object':
            train_df['Rolling_Performance'] = pd.to_numeric(train_df['Rolling_Performance'], errors='coerce')
        if test_df['Rolling_Performance'].dtype == 'object':
            test_df['Rolling_Performance'] = pd.to_numeric(test_df['Rolling_Performance'], errors='coerce')

        y_train = train_df['Rolling_Performance'] - train_df['rf']
        y_test = test_df['Rolling_Performance'] - test_df['rf']
        X_train = train_df[['Fund_ID', 'mktrf', 'smb', 'hml', 'rmw', 'cma']]
        X_test = test_df[['Fund_ID', 'mktrf', 'smb', 'hml', 'rmw', 'cma']]

        # Add fund id as a categorical input
        X_train['Fund_ID'] = X_train['Fund_ID'].astype('category').cat.codes
        X_test['Fund_ID'] = X_test['Fund_ID'].astype('category').cat.codes

        # Train the random forest
        rf_model = RandomForestRegressor(n_estimators=100, random_state=42)
        rf_model.fit(X_train, y_train)

        # Predict
        y_pred = rf_model.predict(X_test)

        # Calculate MSE
        mse = mean_squared_error(y_test, y_pred)
        mse_values.append(mse)

        # Collect feature importance
        feature_importances.append(rf_model.feature_importances_)

        # Add results to the results list
        for i in range(len(y_test)):
            results.append({
                'Fund_ID': test_df.iloc[i]['Fund_ID'],
                'Date_fund': test_df.iloc[i]['Date_fund'],
                'Actual': y_test.iloc[i],
                'Predicted': y_pred[i]
            })

        # Print progress during training
        print(f'Trained up to date: {current_date.strftime("%Y-%m")}, Number of test predictions: {len(results)}, MSE: {mse:.4f}')

        # Update current date
        current_date += pd.DateOffset(months=12)

    # Convert the results list to DataFrame
    results_df = pd.DataFrame(results)

    # Calculate mean feature importance
    mean_feature_importances = np.mean(feature_importances, axis=0)
    feature_names = ['Fund_ID', 'mktrf', 'smb', 'hml', 'rmw', 'cma']
    feature_importances_df = pd.DataFrame({'Feature': feature_names, 'Importance': mean_feature_importances})
    feature_importances_df = feature_importances_df.sort_values(by='Importance', ascending=False)

    # Calculate mean MSE
    mean_mse = np.mean(mse_values)
    print(f'Mean MSE: {mean_mse:.4f}')

    return results_df, feature_importances_df

def calculate_alpha_from_results(results_df, interval_months):
    """
    Get Alpha from machine learning results

    Parameters：
    - results_df: Dataframe containing all predictions and actual values
    - interval_months: time interval, 3 or 6 or 12

    Returns：
    - interval_alpha_df: Alpha for each time interval（DataFrame）
    """
    results_df = results_df.sort_values(['Fund_ID', 'Date_fund']).reset_index(drop=True)
    # Calculate the residues
    results_df['Residual'] = results_df['Actual'] - results_df['Predicted']
    interval_alpha_df = pd.DataFrame(columns=['Fund_ID', 'Interval', 'Alpha'])

    # Group by fund ID
    grouped = results_df.groupby('Fund_ID')

    for fund_id, group in grouped:
        group = group.reset_index(drop=True)

        for i in range(0, len(group), interval_months):
            interval_df = group.iloc[i:i + interval_months]
            if len(interval_df) == interval_months:
                # Take time series average of residuals to get alpha
                alpha = interval_df['Residual'].mean()
                # Add to the interval alpha dataframe
                new_row = pd.DataFrame({'Fund_ID': [fund_id], 'Interval': [i // interval_months], 'Alpha': [alpha]})
                interval_alpha_df = pd.concat([interval_alpha_df, new_row], ignore_index=True)

    return interval_alpha_df

def prepare_lagged_alpha_df(alpha_df):
    """
    Create lagged alpha for each fund.

    Parameter：
    alpha_df (DataFrame): contains 'Fund_ID' and 'Alpha'

    Return：
    lagged_alpha_df (DataFrame): new dataframe that contains lagged alpha
    """
    # create a dataframe to store
    lagged_alpha_df = pd.DataFrame()

    # group by fund id and create lagged alpha for each fund
    for fund_id, group in alpha_df.groupby('Fund_ID'):
        group = group.sort_values(by='Interval').reset_index(drop=True)
        group['Lagged_Alpha'] = group['Alpha'].shift(1)
        lagged_alpha_df = pd.concat([lagged_alpha_df, group], ignore_index=True)

    # drop nas
    lagged_alpha_df = lagged_alpha_df.dropna()

    return lagged_alpha_df

def perform_regression(lagged_alpha_df):
    """
    Perform regression, test the correlation of current alpha and previous alpha.

    Parameter：
    lagged_alpha_df: new dataframe that contains lagged alpha

    Return：
    result (RegressionResults): result of regression
    """
    X = lagged_alpha_df['Lagged_Alpha']
    y = lagged_alpha_df['Alpha']
    X = sm.add_constant(X)  # add constant
    model = sm.OLS(y, X).fit()

    return model

def process_and_regress(alpha_dfs):
    """
    Process each alpha dataframe and perform regression to get significant result ratio.

    Parameter：
    alpha_dfs (dict): Dictionary with keys as identifiers and values as dataframes

    Return：
    summary (dict): Summary of regression results and significant ratios
    """
    regression_summaries = {}
    significant_counts = {}

    # Initialize
    for key, alpha_df in alpha_dfs.items():
        lagged_df = prepare_lagged_alpha_df(alpha_df)
        sig_count = 0
        total_count = 0

        for fund_id, group in lagged_df.groupby('Fund_ID'):
            regression_result = perform_regression(group)
            p_value = regression_result.pvalues['Lagged_Alpha']
            total_count += 1
            if p_value < 0.05:  # Using significance level of 5%
                sig_count += 1

        regression_summaries[key] = {
            'total_funds': total_count,
            'significant_funds': sig_count,
            'significance_ratio': sig_count / total_count if total_count > 0 else 0
        }

    return regression_summaries

def generate_factor_summary(df, output_file='factor_summary.xlsx'):
    """
    Generate a summary table of factors and print the table

    Parameters：
    df (DataFrame): DataFrame containing factors，including 'mktrf', 'smb', 'hml', 'rmw', 'cma' and 'umd'。
    """
    # delete date column
    if 'date' in df.columns:
        df = df.drop(columns=['date'])

    # Calculate the mean value of monthly excess return
    monthly_excess_return = df.mean(numeric_only=True)

    # Calcaulte standard deviation
    std_dev = df.std(numeric_only=True)

    # Calcaulte t-stat
    t_stat = monthly_excess_return / (std_dev / np.sqrt(len(df)))

    # Calculate Correlation matrix
    correlation_matrix = df.corr(numeric_only=True)

    # Store in a dataframe
    results_df = pd.DataFrame({
        'Monthly Excess Return': monthly_excess_return,
        'Std Dev': std_dev,
        't-stat for Mean = 0': t_stat
    })

    # Print
    print("Factor Summary")
    print(results_df)

    print("\nCross-Correlations")
    print(correlation_matrix)

def generate_cpr_table(cpr_3m_hedge, z_3m_hedge, chisq_3m_hedge,
                       cpr_6m_hedge, z_6m_hedge, chisq_6m_hedge,
                       cpr_12m_hedge, z_12m_hedge, chisq_12m_hedge,
                       cpr_3m_mutual, z_3m_mutual, chisq_3m_mutual,
                       cpr_6m_mutual, z_6m_mutual, chisq_6m_mutual,
                       cpr_12m_mutual, z_12m_mutual, chisq_12m_mutual):
    """
    Generate a summary table of CPR, z stat and chi-square for each interval and print it out

    Parameters：cpr, z, chisq for each interval for hedge funds and mutual funds

    """
    data = {
        'Panel': ['Quarterly Returns', '', '', 'Half-Yearly Returns', '', '', 'Yearly Returns', '', ''],
        'Fund_Type': ['Hedge Fund', 'Mutual Fund', '', 'Hedge Fund', 'Mutual Fund', '', 'Hedge Fund', 'Mutual Fund', ''],
        'CPR': [
            cpr_3m_hedge, cpr_3m_mutual, '', cpr_6m_hedge, cpr_6m_mutual, '', cpr_12m_hedge, cpr_12m_mutual, ''
        ],
        'Z_Value': [
            z_3m_hedge, z_3m_mutual, '', z_6m_hedge, z_6m_mutual, '', z_12m_hedge, z_12m_mutual, ''
        ],
        'Chi-Square': [
            chisq_3m_hedge, chisq_3m_mutual, '', chisq_6m_hedge, chisq_6m_mutual, '', chisq_12m_hedge, chisq_12m_mutual, ''
        ]
    }


    # create DataFrame
    result_table = pd.DataFrame(data)

    # print
    print(result_table)

def analyze_fund_data(df):
  """
  Give a summary of the fund data, including number of funds, averatge life span

  Parameters:
  df: DataFrame containing fund data

  Returns:
  result_table: DataFrame with summary of fund data

  """
    # convert the Date column to datetime form
    df['Date'] = pd.to_datetime(df['Date'])

    # Group by fund ID, calculate the life cycle of each fund
    fund_lifecycle = df.groupby('Fund_ID')['Date'].agg(['min', 'max'])
    fund_lifecycle['Lifecycle'] = (fund_lifecycle['max'] - fund_lifecycle['min']).dt.days // 30

    # Calculate average life cycle and median life cycle
    average_lifecycle = fund_lifecycle['Lifecycle'].mean()
    median_lifecycle = fund_lifecycle['Lifecycle'].median()

    # Determines whether a fund is active or closed
    # The fund is considered active if the last record date is after May 2024
    active_threshold_date = pd.to_datetime('2024-05-01')
    fund_lifecycle['Status'] = ['Active' if end_date >= active_threshold_date else 'Dead/Acquired' for end_date in fund_lifecycle['max']]

    # summary the number of active and dead funds
    active_fund_count = fund_lifecycle[fund_lifecycle['Status'] == 'Active'].shape[0]
    dead_fund_count = fund_lifecycle[fund_lifecycle['Status'] == 'Dead/Acquired'].shape[0]

    # create a datafrmae
    result_table = pd.DataFrame({
        'Metric': ['Total Funds', 'Active Funds', 'Dead/Acquired Funds', 'Average Lifecycle (months)', 'Median Lifecycle (months)'],
        'Count': [len(fund_lifecycle), active_fund_count, dead_fund_count, average_lifecycle, median_lifecycle]
    })

    return result_table



# Set start date, end date and start date of training
start_date = '2004-05-01'
end_date = '2024-05-31'
train_start = '1994-05-01'

# Get merged datafrmame for six-factor model and machine learning calculations
mutual_factor_df = process_fund_data(mutual_fund_df, factor_df, start_date, end_date, min_months=0)
hedge_factor_df = process_fund_data(hedge_fund_df, factor_df, start_date, end_date, min_months=0)
mutual_factor_rf = process_fund_data(mutual_fund_df, factor_df, train_start, end_date, min_months=0)
hedge_factor_rf = process_fund_data(hedge_fund_df, factor_df, train_start, end_date, min_months=0)

# Summary  hedge fund data
analyze_fund_data(hedge_fund_df)

# Summary hedge fund data
analyze_fund_data(mutual_fund_df)

# Summary factor data
generate_factor_summary(factor_df)

# Calculate Alpha of hedge funds using six factor model
hedge_alpha_3m = calculate_alpha_for_intervals(hedge_factor_df,3)
hedge_alpha_6m = calculate_alpha_for_intervals(hedge_factor_df,6)
hedge_alpha_12m = calculate_alpha_for_intervals(hedge_factor_df,12)

# Calculate Alpha of mutual funds using six factor model
mutual_alpha_3m = calculate_alpha_for_intervals(mutual_factor_df,3)
mutual_alpha_6m = calculate_alpha_for_intervals(mutual_factor_df,6)
mutual_alpha_12m = calculate_alpha_for_intervals(mutual_factor_df,12)

# train and predict for mutual funds using random forest, also get feature importance results
mutual_rf,mutual_importance = train_and_predict(mutual_factor_rf, train_start, start_date, end_date)

# train and predict for mutual funds using random forest, also get feature importance results
hedge_rf, hedge_importance = train_and_predict(hedge_factor_rf, train_start, start_date, end_date)

# Calcaulte Alpha by using predictions and actual values for each interval for both funds
hedge_alpha_3m_rf = calculate_alpha_from_results(hedge_rf, 3)
hedge_alpha_6m_rf = calculate_alpha_from_results(hedge_rf, 6)
hedge_alpha_12m_rf = calculate_alpha_from_results(hedge_rf, 12)
mutual_alpha_3m_rf = calculate_alpha_from_results(mutual_rf, 3)
mutual_alpha_6m_rf = calculate_alpha_from_results(mutual_rf, 6)
mutual_alpha_12m_rf = calculate_alpha_from_results(mutual_rf, 12)

# store all dataframes in a dictionary
alpha_dfs = {
    'mutual_3m': mutual_alpha_3m,
    'mutual_6m': mutual_alpha_6m,
    'mutual_12m': mutual_alpha_12m,
    'hedge_3m': hedge_alpha_3m,
    'hedge_6m': hedge_alpha_6m,
    'hedge_12m': hedge_alpha_12m,
    'mutual_3m_rf': mutual_alpha_3m_rf,
    'mutual_6m_rf': mutual_alpha_6m_rf,
    'mutual_12m_rf': mutual_alpha_12m_rf,
    'hedge_3m_rf': hedge_alpha_3m_rf,
    'hedge_6m_rf': hedge_alpha_6m_rf,
    'hedge_12m_rf': hedge_alpha_12m_rf
}

# Construct contingency table for six factor model Alphas
hedge_contingency_table_3m = construct_contingency_table(hedge_alpha_3m)
hedge_contingency_table_6m = construct_contingency_table(hedge_alpha_6m)
hedge_contingency_table_12m = construct_contingency_table(hedge_alpha_12m)
mutual_contingency_table_3m = construct_contingency_table(mutual_alpha_3m)
mutual_contingency_table_6m = construct_contingency_table(mutual_alpha_6m)
mutual_contingency_table_12m = construct_contingency_table(mutual_alpha_12m)

# Construct contingency table for machine learning model Alphas
hedge_contingency_table_3m_rf = construct_contingency_table(hedge_alpha_3m_rf)
hedge_contingency_table_6m_rf = construct_contingency_table(hedge_alpha_6m_rf)
hedge_contingency_table_12m_rf = construct_contingency_table(hedge_alpha_12m_rf)
mutual_contingency_table_3m_rf = construct_contingency_table(mutual_alpha_3m_rf)
mutual_contingency_table_6m_rf = construct_contingency_table(mutual_alpha_6m_rf)
mutual_contingency_table_12m_rf = construct_contingency_table(mutual_alpha_12m_rf)

print(hedge_contingency_table_3m)

# Calculate cpr, z and chi-sq test results for six factor model Alpha contingency table
cpr_3m_hedge, z_3m_hedge, chisq_3m_hedge = calculate_cpr_z_chisq(hedge_contingency_table_3m)
cpr_6m_hedge, z_6m_hedge, chisq_6m_hedge = calculate_cpr_z_chisq(hedge_contingency_table_6m)
cpr_12m_hedge, z_12m_hedge, chisq_12m_hedge = calculate_cpr_z_chisq(hedge_contingency_table_12m)
cpr_3m_mutual, z_3m_mutual, chisq_3m_mutual = calculate_cpr_z_chisq(mutual_contingency_table_3m)
cpr_6m_mutual, z_6m_mutual, chisq_6m_mutual = calculate_cpr_z_chisq(mutual_contingency_table_6m)
cpr_12m_mutual, z_12m_mutual, chisq_12m_mutual = calculate_cpr_z_chisq(mutual_contingency_table_12m)

# Display the results in a table
CPR_table_6factor = generate_cpr_table(cpr_3m_hedge, z_3m_hedge, chisq_3m_hedge,
                       cpr_6m_hedge, z_6m_hedge, chisq_6m_hedge,
                       cpr_12m_hedge, z_12m_hedge, chisq_12m_hedge,
                       cpr_3m_mutual, z_3m_mutual, chisq_3m_mutual,
                       cpr_6m_mutual, z_6m_mutual, chisq_6m_mutual,
                       cpr_12m_mutual, z_12m_mutual, chisq_12m_mutual)

# Calculate cpr, z and chi-sq test results for machine learning Alpha contingency table
cpr_3m_hedge_rf, z_3m_hedge_rf, chisq_3m_hedge_rf = calculate_cpr_z_chisq(hedge_contingency_table_3m_rf)
cpr_6m_hedge_rf, z_6m_hedge_rf, chisq_6m_hedge_rf = calculate_cpr_z_chisq(hedge_contingency_table_6m_rf)
cpr_12m_hedge_rf, z_12m_hedge_rf, chisq_12m_hedge_rf = calculate_cpr_z_chisq(hedge_contingency_table_12m_rf)
cpr_3m_mutual_rf, z_3m_mutual_rf, chisq_3m_mutual_rf = calculate_cpr_z_chisq(mutual_contingency_table_3m_rf)
cpr_6m_mutual_rf, z_6m_mutual_rf, chisq_6m_mutual_rf = calculate_cpr_z_chisq(mutual_contingency_table_6m_rf)
cpr_12m_mutual_rf, z_12m_mutual_rf, chisq_12m_mutual_rf = calculate_cpr_z_chisq(mutual_contingency_table_12m_rf)

# Display the results in a table
CPR_table_ml = generate_cpr_table(cpr_3m_hedge_rf, z_3m_hedge_rf, chisq_3m_hedge_rf,
                       cpr_6m_hedge_rf, z_6m_hedge_rf, chisq_6m_hedge_rf,
                       cpr_12m_hedge_rf, z_12m_hedge_rf, chisq_12m_hedge_rf,
                       cpr_3m_mutual_rf, z_3m_mutual_rf, chisq_3m_mutual_rf,
                       cpr_6m_mutual_rf, z_6m_mutual_rf, chisq_6m_mutual_rf,
                       cpr_12m_mutual_rf, z_12m_mutual_rf, chisq_12m_mutual_rf)

# Display ks test result using binomial distribution as theoretical distribution
binomial_table = generate_binomial_table(hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                                         mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                                         hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                                         mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf)

print(binomial_table)

# Display ks test result using binomial distribution as theoretical distribution
normal_table = generate_normal_table(hedge_alpha_3m, hedge_alpha_6m, hedge_alpha_12m,
                                     mutual_alpha_3m, mutual_alpha_6m, mutual_alpha_12m,
                                     hedge_alpha_3m_rf, hedge_alpha_6m_rf, hedge_alpha_12m_rf,
                                     mutual_alpha_3m_rf, mutual_alpha_6m_rf, mutual_alpha_12m_rf)
print(normal_table)

#Perform regression and display result
regression_result = process_and_regress(alpha_dfs)
print(regression_result)

# Show result of feature importance analysis for mutual fund
mutual_importance

# Show result of feature importance analysis for hedge fund
hedge_importance

