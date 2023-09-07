# -*- coding: utf-8 -*-
"""Neural-Collaborative-Filtering.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1-onJD2nN6wliQpG3b5uFX5J4_vzjFOaq
"""

import pandas as pd
import numpy as np
import scipy.sparse as sp
import json

"""# CF Using Neural Collaborative Filtering
In the world of reccomender sytems, collabrative filtering is usually done through matrix factorization using the inner product on the latent features of users and items. According to Xiangnan He from the National University of Sigapore, forcing the features to be orthgonal using the inner product limits the features that can be extracted. He believes this can have significant performance implicaitons especially when dealing with implifict feedback (1 if consumed, 0 if not consumed) where natural negative feedback is not easily availible.

In his paper entitled, [Nerual Collaborative Filtering](https://arxiv.org/pdf/1708.05031.pdf) He argues that using a nueral network to do the dimentionality reduction is a form of general matrix factorization (GMF) that can improve performance. Here we explore that possibility using Spotify's 1M Challenge Data.

Below is his proposed network for GMF that we will implement on a subset of our 1M Challenge Data.

![GMF.png](GMF.png)

## Preparing Dataset
Let's begin by reading in our dataset.
"""

#Create a function to read in json
def readin_json(start):
    if start not in np.arange(0, 1000000, 1000):
        raise Exception('Invalid start pid! Start pids must be {0, 1000, 2000, ..., 999000}')
    end=start+1000
    path = 'data/mpd.slice.' + str(start) + "-" + str(end-1) + '.json'
    d = json.load(open(path, 'r'))
    thisslice = pd.DataFrame.from_dict(d['playlists'], orient='columns')
    return thisslice

#Read in a subset of our 1M Playlists
first1000 = readin_json(0)
second1000 = readin_json(1000)
third1000 = readin_json(2000)
traindata = pd.concat([first1000, second1000, third1000])

#Also read in the challenge dataset which has missing songs we
#want our model to predict
t = json.load(open('data/challenge_set.json'))
challenge_df = pd.DataFrame.from_dict(t['playlists'], orient='columns')
#Combine train and challenge so we can use cat code to map
#track ids to an index 0-N across both datasets
train_challengedata = pd.concat([traindata, challenge_df])

#Turn playlist level dataframe into song level dataframe
songPlaylistArray = []
for index, row in train_challengedata.iterrows():
    for track in row['tracks']:
        songPlaylistArray.append([track['track_uri'], track['artist_name'], track['track_name'], row['pid'], row['num_holdouts']])
songPlaylist = pd.DataFrame(songPlaylistArray, columns=['trackid', 'artist_name', 'track_name', 'pid', 'num_holdouts'])

print(songPlaylist.shape)
songPlaylist.head(10)   #is a df of all track ids, cooresponding artist names, track names and playlist ids

# Turn songs into their unqiue cat codes so we have a 0-N index for tracks
songPlaylist['trackindex'] = songPlaylist['trackid'].astype('category').cat.codes
print(len(songPlaylist['trackindex'].unique()))
songPlaylist.head(10)

# split appart training and challenge data
train = songPlaylist[pd.isnull(songPlaylist['num_holdouts'])]
challenge = songPlaylist[pd.notnull(songPlaylist['num_holdouts'])]

train.head(10)

#Save data in dok matrix (optimized sparse matrix object)
    #Create a sparse pid x trackindex matrix
    #If a pid i has song j, mat[i,j]=1
mat = sp.dok_matrix((3000, 110716), dtype=np.float32)
for pid, trackindex in zip(train['pid'], train['trackindex']):
    mat[pid, trackindex] = 1.0

"""## Building and NN Using Keras"""

import numpy as np
import theano.tensor as T
import keras
from keras import backend as K
from keras import initializations
from keras.models import Sequential, Model, load_model, save_model
from keras.layers.core import Dense, Lambda, Activation
from keras.layers import Embedding, Input, Dense, merge, Reshape, Merge, Flatten
from keras.optimizers import Adam
from keras.regularizers import l2
from time import time
import multiprocessing as mp
import sys
import math

def init_normal(shape, name=None):
    return initializations.normal(shape, scale=0.01, name=name)

def get_model(num_playlists, num_items, latent_dim, regs=[0,0]):
    # Input variables
    playlist_input = Input(shape=(1,), dtype='int32', name = 'playlist_input')
    item_input = Input(shape=(1,), dtype='int32', name = 'item_input')

    MF_Embedding_playlist = Embedding(input_dim = num_playlists, output_dim = latent_dim, name = 'playlist_embedding',
                                  init = init_normal, W_regularizer = l2(regs[0]), input_length=1)
    MF_Embedding_Item = Embedding(input_dim = num_items, output_dim = latent_dim, name = 'item_embedding',
                                  init = init_normal, W_regularizer = l2(regs[1]), input_length=1)

    # Crucial to flatten an embedding vector!
    playlist_latent = Flatten()(MF_Embedding_playlist(playlist_input))
    item_latent = Flatten()(MF_Embedding_Item(item_input))

    # Element-wise product of playlist and item embeddings
    predict_vector = merge([playlist_latent, item_latent], mode = 'mul')

    # Final prediction layer
    #prediction = Lambda(lambda x: K.sigmoid(K.sum(x)), output_shape=(1,))(predict_vector)
    prediction = Dense(1, activation='sigmoid', init='lecun_uniform', name = 'prediction')(predict_vector)

    model = Model(input=[playlist_input, item_input],
                output=prediction)
    return model

def get_train_instances(train, num_negatives):
    playlist_input, item_input, labels = [],[],[]
    num_playlists = train.shape[0]
    for (u, i) in train.keys():
        # positive instance
        playlist_input.append(u)
        item_input.append(i)
        labels.append(1)
        # negative instances
        for t in xrange(num_negatives):
            j = np.random.randint(num_items)
            while train.has_key((u, j)):
                j = np.random.randint(num_items)
            playlist_input.append(u)
            item_input.append(j)
            labels.append(0)
    return playlist_input, item_input, labels

# Specify hyperparameters
num_factors = 8
regs = [0,0]
num_negatives = 4
learner = 'adam'
learning_rate = 0.001
epochs = 15
batch_size = 200
verbose = 1

# Save model
model_out_file = './GMF_%d_%d.h5' %(num_factors, time())

# Loading data
train = mat
num_playlists, num_items = train.shape
print("Load data done")

# Build model
model = get_model(num_playlists, num_items, num_factors, regs)
model.compile(optimizer=Adam(lr=learning_rate), loss='binary_crossentropy', metrics=['accuracy'])
print(model.summary())

# Train model
for epoch in xrange(epochs):
    # Generate training instances
    playlist_input, item_input, labels = get_train_instances(train, num_negatives)

    # Training
    hist = model.fit([np.array(playlist_input), np.array(item_input)], #input
                     np.array(labels), # labels
                     validation_split=0.20, batch_size=batch_size, nb_epoch=1, verbose=0, shuffle=True)
    print(hist.history)



"""## Generating Reccomendations for Challenge Playlists

Having trained our model, we will use our model to predict the missing songs in the challenge playlist. Altough, to be able to predict new songs for a playlist it must first exist in our training data. Only then can the network looks up the playlist in the seed track, look at the similarity to other training data and reccomend songs.

This means that everytime we want to predict songs for a playlist we must retrain the data! This approach is not compuationally efficient considering that we can't even load in our full dataset. We might need to use a different stack and different approach for our playlist reccomender.
"""