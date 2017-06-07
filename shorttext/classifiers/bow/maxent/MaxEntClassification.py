
import pickle

from scipy.sparse import dok_matrix
from gensim.corpora import Dictionary
from keras.models import Sequential
from keras.layers import Dense
from keras.regularizers import l2

import shorttext.utils.kerasmodel_io as kerasio
from shorttext.utils import tokenize
from shorttext.utils import gensim_corpora as gc
from shorttext.utils import classification_exceptions as e
import shorttext.utils.compactmodel_io as cio
from shorttext.utils import deprecated


def logistic_framework(nb_features, nb_outputs, l2reg=0.01, bias_l2reg=0.01, optimizer='adam'):
    """ Construct the neural network of maximum entropy classifier.

    Given the numbers of features and the output labels, return a keras neural network
     for implementing maximum entropy (multinomial) classifier.

    :param nb_features: number of features
    :param nb_outputs: number of output labels
    :param l2reg: L2 regularization coefficient (Default: 0.01)
    :param bias_l2reg: L2 regularization coefficient for bias (Default: 0.01)
    :param optimizer: optimizer for gradient descent. Options: sgd, rmsprop, adagrad, adadelta, adam, adamax, nadam. (Default: adam)
    :return: keras sequential model for maximum entropy classifier
    :type nb_features: int
    :type nb_outputs: int
    :type l2reg: float
    :type bias_l2reg: float
    :type optimizer: str
    :rtype: keras.model.Sequential
    """
    kmodel = Sequential()
    kmodel.add(Dense(units=nb_outputs,
                     activation='softmax',
                     input_shape=(nb_features,),
                     kernel_regularizer=l2(l2reg),
                     bias_regularizer=l2(bias_l2reg))
               )
    kmodel.compile(loss='categorical_crossentropy', optimizer=optimizer)
    return kmodel


@cio.compactio({'classifier': 'maxent'}, 'maxent', ['_classlabels.txt', '.json', '.h5', '_labelidx.pkl', '_dictionary.dict'])
class MaxEntClassifier:
    def __init__(self, preprocessor=lambda s: s.lower()):
        self.preprocessor = preprocessor
        self.trained = False

    @deprecated
    def shorttext_to_vec(self, shorttext):
        # too slow, deprecated
        tokens = tokenize(self.preprocessor(shorttext))

        vec = dok_matrix((1, len(self.dictionary)))
        for token in tokens:
            vec[0, self.dictionary.token2id[token]] = 1.0

        return vec[0, :]

    @deprecated
    def gensimcorpus_to_matrix(self, corpus):
        # not used, deprecated
        matrix = dok_matrix((len(corpus), len(self.dictionary)))
        for docid, doc in enumerate(corpus):
            for tokenid, count in doc:
                matrix[docid, tokenid] = count
        return matrix

    def index_classlabels(self):
        self.labels2idx = {label: idx for idx, label in enumerate(self.classlabels)}

    def convert_classdict_to_XY(self, classdict):
        nb_data = sum(map(lambda k: len(classdict[k]), classdict.keys()))
        X = dok_matrix((nb_data, len(self.dictionary)))
        y = dok_matrix((nb_data, len(self.labels2idx)))

        rowid = 0
        for label in classdict:
            if label in self.labels2idx.keys():
                for shorttext in classdict[label]:
                    tokens = tokenize(self.preprocessor(shorttext))
                    #X[rowid, :] = self.shorttext_to_vec(shorttext)
                    for token in tokens:
                        X[rowid, self.dictionary.token2id[token]] += 1.0
                    y[rowid, self.labels2idx[label]] = 1.
                    rowid += 1

        return X, y

    def train(self, classdict, nb_epochs=500, l2reg=0.01, bias_l2reg=0.01, optimizer='adam'):
        self.dictionary, self.corpus, self.classlabels = gc.generate_gensim_corpora(classdict,
                                                                                    preprocess_and_tokenize=lambda s: tokenize(self.preprocessor(s)))
        self.index_classlabels()

        X, y = self.convert_classdict_to_XY(classdict)

        kmodel = logistic_framework(len(self.dictionary),
                                    len(self.classlabels),
                                    l2reg=l2reg,
                                    bias_l2reg=bias_l2reg,
                                    optimizer=optimizer)
        kmodel.fit(X.toarray(), y.toarray(), epochs=nb_epochs)

        self.model = kmodel
        self.trained = True

    def savemodel(self, nameprefix):
        if not self.trained:
            raise e.ModelNotTrainedException()

        kerasio.save_model(nameprefix, self.model)

        self.dictionary.save(nameprefix+'_dictionary.dict')

        labelfile = open(nameprefix+'_classlabels.txt', 'w')
        labelfile.write('\n'.join(self.classlabels))
        labelfile.close()

        pickle.dump(self.labels2idx, open(nameprefix+'_labelidx.pkl', 'w'))

    def loadmodel(self, nameprefix):
        self.model = kerasio.load_model(nameprefix)

        self.dictionary = Dictionary.load(nameprefix+'_dictionary.dict')

        labelfile = open(nameprefix+'_classlabels.txt', 'r')
        self.classlabels = labelfile.readlines()
        labelfile.close()
        self.classlabels = map(lambda s: s.strip(), self.classlabels)

        self.labels2idx = pickle.load(open(nameprefix+'_labelidx.pkl', 'r'))

        self.trained = True

    def score(self, shorttext):
        if not self.trained:
            raise e.ModelNotTrainedException()

        vec = self.shorttext_to_vec(shorttext)
        predictions = self.model.predict(vec.toarray())

        # wrangle output result
        scoredict = {classlabel: predictions[0][idx] for idx, classlabel in enumerate(self.classlabels)}
        return scoredict

def load_maxent_classifier(name, compact=True):
    classifier = MaxEntClassifier()
    if compact:
        classifier.load_compact_model(name)
    else:
        classifier.loadmodel(name)
    return classifier