## Post Processing of MaxQuant output (proteinGroups.txt)

import itertools
import matplotlib.pyplot as plt
from numpy import logical_or
import numpy as np
import pandas as pd
import re
from scipy.cluster.hierarchy import dendrogram, linkage
import scipy.stats as stats
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn import preprocessing


"""
Args: 
    file (str): path to tab separated proteinGroups.txt file outputted from MaxQuant
    
Returns:
    dataframe: dataframe containing data from the file
"""
def load_df(file):
    df = pd.read_csv(file, sep='\t', lineterminator='\r', dtype={"Only identified by site": str, "Reverse": str, "Potential contaminant": str})
    return df


"""
Args: 
    df (dataframe): assumes columns 'Only identified by site', 'Reverse', 'Potential contaminant'
    
Returns:
    df: Dataframe with rows having a '+' in any of these columns removed
"""
def clean_weakly_identified(df):
    df = df[(df['Only identified by site'] != '+') & (df.Reverse != '+') & (df['Potential contaminant'] != '+')]
    return df


"""
Args: 
    df (dataframe)
    
Returns:
    df: Dataframe where rows containing multiple protein IDs have been removed
"""
def remove_dup_proteinIDs(df):
    single_proteinID = df['Majority protein IDs'].str.contains(';') == False
    df = df[single_proteinID]
    return df


"""
Args: 
    df (dataframe)
    feature (string): 'protein' or 'peptide' depending which type of data we are looking at
    col_name (string): 'iBAQ ' or 'LFQ'
    
Returns: 
    dataframe: input dataframe filtered to contain the protein ID column and columns containing the input string
"""

def slice_by_column(df, feature, col_name):
    if feature == 'protein':
        selected_col_name = col_name + ".*|Majority protein IDs"
    else:
        selected_col_name = col_name + ".*|Sequence"
        
    df_slice = df.filter(regex = selected_col_name)
    return df_slice


#########################
#
# Filter out proteins where quant value is 0 for >= 50% of samples for all organs
#
#########################
"""
Args: 
    df (dataframe)
    groups (list of strings): list of organs or group names by which column names will be sorted
    organ_columns (dict)
    organ_counts (dict)
    
Returns:
    df: filtered dataframe where proteins not observed in at least 50% of samples in any group have been removed
"""
def filter_low_observed(df, groups, organ_columns, organ_counts):
    df_cols = df.columns.values.tolist()
    
    for group in groups:
        regex = re.compile(r'.*' + group)
        organ_columns[group] = list(filter(regex.search, df_cols))
        cols = organ_columns[group] # Get corresponding list of column names
        threshold = len(cols)/2
        organ_counts[group] = (df[cols] > 0).sum(1) # count number of samples with non-zero abundance for each protein
        
    conditions = list(organ_counts[g] >= threshold for g in groups)
    df = df[logical_or.reduce(conditions)]
    return df


#########################
#
# Unnormalized data abundances 
#
#########################

"""
Args:
    df (dataframe)
    base_dir (string): path to directory to place image
    title (string): graph title, no extension
    dimensions (integer tuple, optional): tuple of integers representing plot width and height
    
Returns:
    produces a boxplot and saves it as a pdf in the given base directory
"""

def make_boxplot(df, base_dir, title, dimensions = (10, 6)):
    df.boxplot(return_type='axes', figsize = dimensions)
    plt.xticks(rotation='vertical')
    output_path = base_dir + title + '.pdf'
    plt.savefig(output_path, bbox_inches="tight")
    plt.clf()


#########################
#
# log2 normalize
#
#########################

"""
Args:
    df (dataframe)
    
Returns:
    log2 normalizes dataframe values in place
"""
def log2_normalize(df):
    df.iloc[:,1:] = df.iloc[:,1:].applymap(np.log2)
    # log2(0) returns -inf; replace with NaN to avoid skewing data
    df.replace([np.inf, -np.inf], np.nan, inplace=True)


#########################
#
# Map organs to colors for visualization clarity 
#
#########################
"""
Args:
    groups (list of strings): list of organs or column names to be grouped together by color
    organ_columns (dict): keys are strings representing organs/groups, values are lists of associated column names

Returns: 
    dict: dictionary mapping column names to colors based on organ/group
"""
def map_colors(groups, organ_columns):
    color_dict = {} # Column name : color
    num_colors = 6
    colors = sns.color_palette("hls", num_colors)
    color = 0

    for organ in groups:
        cols = organ_columns[organ] # Get the list of column names for the organ
        for col in cols:
            color_dict[col] = colors[color % len(colors)]
        color += 1
        
    return color_dict

"""
Args:
    df (dataframe)
    base_dir (string): base directory for image
    title (string): plot title, no extension
    colors (dict): dictionary mapping column names to colors
    dimensions (tuple of ints, optional): tuple of integers representing plot width and height
    
Returns:
    produces a seaborn boxplot and saves it as a pdf in the given base directory
"""
def make_seaborn_boxplot(df, base_dir, title, colors, dimensions = (10, 6)):

    fig, ax = plt.subplots(figsize = dimensions)
    ax.set_xticklabels(ax.get_xticklabels(), rotation = 90)
    sns.boxplot(data = df, palette = colors, ax = ax)
    output_path = base_dir + title + '.pdf'
    plt.savefig(output_path, bbox_inches = "tight")
    plt.clf()


#########################
#
# Median normalize
#
#########################

"""
Args:
    df (dataframe)
    
Returns:
    median-normalizes the dataframe in-place
"""

def median_normalize(df):
    quants = df.iloc[:,1:] # Split off iBAQ columns to process
    median_of_medians = quants.median().median()
    quants /= quants.median(axis = 0) # divide each value by sample median
    quants *= median_of_medians # multiply each value by median of medians

    df.iloc[:,1:] = quants # insert processed iBAQ values into original df


#########################
#
# Impute missing values
#
#########################

"""
Args:
    df (dataframe)

Returns:
    the input dataframe modified so that missing values are replaced by half the minimum value
"""
def impute_missing(df):
    df_min = df.iloc[:,1:].min().min()
    impute_val = df_min/2
    df = df.fillna(impute_val)
    return df


#########################
#
# Perform PCA on the data
#
#########################

"""
Args: 
    df (dataframe)
    
Returns: 
    pca, pca_data (tuple): PCA object, PCA coordinates for dataframe
"""
def do_pca(df):
    
    # Check if index has already been set:
    if type(df.index) == pd.core.indexes.numeric.Int64Index:
        df.set_index('Majority protein IDs', inplace=True)
    
    scaled_data = preprocessing.scale(df.T)

    pca = PCA() # create a PCA object
    pca.fit(scaled_data) # do the math
    pca_data = pca.transform(scaled_data) # get PCA coordinates for dataframe
    
    return(pca, pca_data)
    
#########################
#
# Draw a scree plot 
#
#########################

"""
Args:
    pca (PCA): first object in tuple returned from do_pca
    base_dir (string): path to directory to place image
    
Returns:
    produces a scree plot and saves it as a pdf in the given base directory
    per_var, labels (tuple)
"""
def make_scree_plot(pca, base_dir):

    per_var = np.round(pca.explained_variance_ratio_* 100, decimals = 1)
    labels = ['PC' + str(x) for x in range(1, len(per_var)+1)]
 
    plt.bar(x = range(1, len(per_var) + 1), height = per_var, tick_label = labels)
    plt.ylabel('Percentage of Explained Variance')
    plt.xlabel('Principal Component')
    plt.title('Scree Plot')
    plt.xticks(rotation='vertical')
    output_path = base_dir + 'Scree.pdf'

    plt.savefig(output_path, bbox_inches="tight")
    plt.clf()
    
    return(per_var, labels)

#########################
#
# Draw PCA Graph 
#
#########################

"""
Args:
    column_names (list of strings):
    pca_data (): PCA coordinates
    base_dir (string): path to directory to place image
    color_dict (dict)
    per_var:
    labels:
    
Returns:
    produces a PCA plot and saves it as a pdf in the given base directory
"""
def draw_pca_graph(column_names, pca_data, base_dir, color_dict, per_var, labels):
    
    pca_df = pd.DataFrame(pca_data, index = column_names, columns = labels)
 
    plt.title('PCA Graph')
    plt.xlabel('PC1 - {0}%'.format(per_var[0]))
    plt.ylabel('PC2 - {0}%'.format(per_var[1]))
 
    for column in pca_df.index:
        plt.scatter(pca_df.PC1.loc[column], pca_df.PC2.loc[column], color = color_dict[column])
        plt.annotate(column, (pca_df.PC1.loc[column], pca_df.PC2.loc[column]), color = color_dict[column])

    output_path = base_dir + 'PCA.pdf'
    plt.savefig(output_path, bbox_inches="tight")
    plt.clf()


#########################
#
# Determine which proteins had the biggest influence on PC1 
#
#########################

"""
Args:
    pca (PCA)
    df (dataframe)
    n (int): number of proteins to return; e.g. 10 for the top 10 proteins with the biggest influence on PC1
    
Returns:
    list of tuples: first element of each tuple is the proteinID, second element is the protein's loading score
"""

def top_n_loading_scores(pca, df, n):
    
    loading_scores = pd.Series(pca.components_[0], index = df.index)
    sorted_loading_scores = loading_scores.abs().sort_values(ascending = False)

    top_proteins = sorted_loading_scores[0:n].index.values
    return loading_scores[top_proteins]


#########################
#
# Pearson correlation of the samples compared to each other 
#
#########################
"""
Args:
    df (dataframe)
    base_dir (string): path to directory to place image
    colormap (string, optional): seaborn colormap code. Defaults to a red-blue spectrum
    dimensions (tuple of ints, optional): tuple of integers representing plot width and height
    
Returns:
    produces a Pearson matrix plot and saves it as a pdf in the given base directory
"""

def make_pearson_matrix(df, base_dir, colormap = "RdBu_r", dimensions = (16, 11)):

    fig, ax = plt.subplots(figsize = dimensions)
    ax.set_title('Pearson Correlations', size = 20)

    corr = df.corr(method = 'pearson')
    sns.heatmap(corr, 
                xticklabels = corr.columns.values,
                yticklabels = corr.columns.values,
                annot = True, # Show numerical values in each box
                cmap = colormap, 
                ax = ax) 
    
    output_path = base_dir + 'Pearson_Matrix.pdf'
    plt.savefig(output_path, bbox_inches="tight")
    plt.clf()


#########################
#
# Hierarchical clustering of proteins
#
#########################
"""
Args:
    df (dataframe)
    base_dir (string): path to directory to place image
    dimensions (tuple of ints, optional): tuple of integers representing plot width and height
    
Returns:
    produces a hierarchical cluster plot and saves it as a pdf in the given base directory
"""
def hierarchical_cluster(df, base_dir, dimensions = (10, 6)):

    z = linkage(df.values, method='ward')

    plt.figure(figsize = dimensions)
    plt.title('Hierarchical Clustering of Proteins')
    plt.ylabel('distance')
    dendrogram(z,
               leaf_rotation=90.,  # rotates the x axis labels
               #leaf_font_size=8.,  # font size for the x axis labels
              )
    
    output_path = base_dir + 'Hierarchical_Clustering.pdf'
    plt.savefig(output_path, bbox_inches="tight")
    plt.clf()


# ## ANOVA and t-tests

"""
Args:
    df (dataframe)
    pval (float): p-value; .05 corresponds to 5%
    
Returns:
    dataframe: input dataframe filtered to only include proteins passing ANOVA with the given p-value
"""
def filter_proteins_by_anova(df, pval):
    # Build list of proteins that pass ANOVA
    pass_anova = []
    max_pval = pval
    proteins = list(df.index)

    # Perform ANOVA on each row (protein) grouping by organ
    # If the protein passes ANOVA (p-value <= max_pval), add it to the list of proteins to keep
    for i in range(len(df)): 
        f, p = stats.f_oneway(df.iloc[i, :6],
                              df.iloc[i, 6:12],
                              df.iloc[i, 12:18], 
                              df.iloc[i, 18:24], 
                              df.iloc[i, 24:30])
        if p <= max_pval:
            pass_anova.append(proteins[i])

    # Filter dataframe down to only include proteins in pass_anova
    pass_anova_df = df[df.index.isin(pass_anova)]
    return pass_anova_df

#########################
#
# Heatmap of proteins
#
#########################

"""
Args:
    df (dataframe)
    base_dir (string): path to directory to place image
    colormap (string, optional): seaborn colormap code. Defaults to a red-blue spectrum
    
Returns:
    produces a heatmap and saves it as a pdf in the given base directory
"""
def protein_heatmap(df, base_dir, colormap = "RdBu_r"):

    sns.clustermap(df,
                   method = 'ward',
                   z_score = 1, # on columns
                   cmap = colormap)

    output_path = base_dir + 'Proteins_Passing_ANOVA_Heatmap.pdf'
    plt.savefig(output_path, bbox_inches = "tight")
    plt.clf()


#########################
#
# Tukey Test
#
#########################


"""
Args:
    df (dataframe)
    organs (list of strings)
    organ_to_columns (dict): mapping of each organ to its associated column names
    
Returns:
    df where columns have been re-ordered to cluster by organ
"""
def reorder_columns(df, organs, organ_to_columns):
    all_cols = list(organ_to_columns[o] for o in organs)
    merged = list(itertools.chain.from_iterable(all_cols))
    df = df[['Majority protein IDs'] + merged]
    return df

#########################
#
# Full Pipeline 
#
#########################
"""
Runs a spreadsheet through the process of cleaning and analyzing, producing charts

Args: 
    file (string): path to proteinGroupt.txt file
    groups (list of strings): list of organ/group names (e.g. ['Brain', 'Lung' ...])
    image_dir (string): directory for images to be saved into. Must already exist
    
Returns: 
    dataframe: Log2 and median normalized dataframe (missing values not imputed). Images will be saved into image_dir
"""
def mq_pipeline(file, groups, image_dir):
    default_dimensions = (10, 6)
    df = load_df(file)
    df = clean_weakly_identified(df)
    df = remove_dup_proteinIDs(df)
        
    iBAQ_df = slice_by_column(df, 'protein', 'iBAQ ') 
    #LFQ_df = slice_by_column(df, 'protein', 'LFQ') 
    
    organ_columns = {} # 'Liver': ['iBAQ 04_Liver', 'iBAQ 05_Liver', ...]
    organ_counts = {} # 'Liver': 
    
    iBAQ_df = filter_low_observed(iBAQ_df, groups, organ_columns, organ_counts)
    make_boxplot(iBAQ_df, image_dir, 'Unnormalized Protein Abundances')
    
    # Group columns by organ so x-axis will be sorted accordingly
    iBAQ_df = reorder_columns(iBAQ_df, groups, organ_columns)
    
    ### Normalize and produce box plots
    log2_normalize(iBAQ_df)
    color_dict = map_colors(groups, organ_columns)
    make_seaborn_boxplot(iBAQ_df, image_dir, 'Log2 Transformed Boxplot', color_dict)
    median_normalize(iBAQ_df)
    make_seaborn_boxplot(iBAQ_df, image_dir, 'Median Normalized Boxplot', color_dict)
    
    ### PCA
    imputed_iBAQ_df = impute_missing(iBAQ_df.copy())
    pca, pca_data = do_pca(imputed_iBAQ_df)
    
    per_var, labels = make_scree_plot(pca, image_dir) 
    column_names = imputed_iBAQ_df.columns.values.tolist()
    draw_pca_graph(column_names, pca_data, image_dir, color_dict, per_var, labels)
    make_pearson_matrix(imputed_iBAQ_df, image_dir)
    hierarchical_cluster(imputed_iBAQ_df, image_dir)
    
    pval = 0.05
    pass_anova_df = filter_proteins_by_anova(imputed_iBAQ_df, pval)
    protein_heatmap(pass_anova_df, image_dir)
    
    return iBAQ_df
