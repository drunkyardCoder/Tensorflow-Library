#!/Prhl/bin/env python
#Author- Prahlad kumar
#contact- prahladk09@gmail.com
#Training OCR data upto 5 LSTM layer

from __future__ import print_function

import random as pyrandom
import re
import os.path
import traceback
import argparse
import sys

import numpy as np
import matplotlib.pyplot as plt

import ocrolib
import ocrolib.lstm as lstm
from ocrolib import lineest

np.seterr(divide='raise',over='raise',invalid='raise',under='ignore')

parser = argparse.ArgumentParser("train an RNN recognizer")

# line normalization
parser.add_argument("-e","--lineest",default="center",
                    help="type of text line estimator, default: %(default)s")
parser.add_argument("-E","--nolineest",action="store_true",
                    help="don't perform line estimation and load .dew.png file")
parser.add_argument("-l","--height",default=48,type=int,
                    help="set the default height for line estimation, default: %(default)s")
parser.add_argument("--dewarp",action="store_true",
                    help="only perform line estimation and output .dew.png file")

# character set
parser.add_argument("-c","--codec",default=[],nargs='*',
                    help="construct a codec from the input text")

# learning
parser.add_argument("-C","--clstm",action="store_true",
                    help="use C++ LSTM")
parser.add_argument("-r","--lrate",type=float,default=1e-4,
                    help="LSTM learning rate, default: %(default)s")
parser.add_argument("-S","--hiddensize",type=int,default=100,
                    help="# LSTM state units, default: %(default)s")
parser.add_argument("-o","--output",default=None,
                    help="LSTM model file")
parser.add_argument("-F","--savefreq",type=int,default=1000,
                    help="LSTM save frequency, default: %(default)s")
parser.add_argument("--strip",action="store_false",
                    help="strip the model before saving")
parser.add_argument("-N","--ntrain",type=int,default=1000000,
                    help="# lines to train before stopping, default: %(default)s")
parser.add_argument("-t","--tests",default=None,
                    help="test cases for error estimation")
parser.add_argument('--unidirectional',action="store_true",
                    help="use only unidirectional LSTM")
parser.add_argument("--updates",action="store_true",
                    help="verbose LSTM updates")
parser.add_argument('--load',default=None,
                    help="start training with a previously trained model")
parser.add_argument('--start',default=-1,type=int,
                    help="manually set the number of already learned lines, which influences the naming and stoping condition, default: %(default)s which will then be overriden by the value saved in the network")

# debugging
parser.add_argument("-X","--exec",default="None",dest="execute",
                    help="execute before anything else (usually used for imports)")
parser.add_argument("-v","--verbose",action="store_true")
parser.add_argument("-d","--display",type=int,default=0,
                    help="display output for every nth iteration, where n=DISPLAY, default: %(default)s")
parser.add_argument("-m","--movie",default=None)
parser.add_argument("-M","--moviesample",default=None)
parser.add_argument("-q","--quiet",action="store_true")
parser.add_argument("-Q","--nocheck",action="store_true")
parser.add_argument("-p","--pad",type=int,default=16)

# add file
parser.add_argument("-f","--file",default=None,help="path to file listing input files, one per line")

parser.add_argument("files",nargs="*")
args = parser.parse_args()

inputs = ocrolib.glob_all(args.files)

if args.file is not None:
    print("getting training data from file")
    with open(args.file) as file:
        for l in file:
            inputs.append(l.rstrip())

if len(inputs)==0:
    parser.print_help()
    sys.exit(0)

print("# inputs", len(inputs))

# pre-execute any python commands

exec args.execute

# make sure movie mode is used correctly

if args.movie is not None:
    if args.display<2:
        print("you must set --display to some number greater than 1")
        sys.exit(0)

if args.moviesample is None:
    args.moviesample = inputs[0]

# make sure an output file has been set

if args.output is None:
    print("you must give an output file with %d in it, or a prefix")
    sys.exit(0)

if not "%" in args.output:
    if args.clstm:
        oname = args.output+"-%08d.h5"
    else:
        oname = args.output+"-%08d.pyrnn"
else:
    oname = args.output

# get a separate test set, if present

tests = None
if args.tests is not None:
    tests = ocrolib.glob_all(args.tests.split(":"))
print("# tests", len(tests) if tests is not None else "None")

# load the line normalizer

if args.lineest=="center":
    lnorm = lineest.CenterNormalizer()
else:
    raise Exception(args.lineest+": unknown line normalizer")
lnorm.setHeight(args.height)

# The `codec` maps between strings and arrays of integers.

if args.codec!=[]:
    print("# building codec")
    codec = lstm.Codec()
    charset = set()
    print(args.codec)
    for fname in ocrolib.glob_all(args.codec):
        transcript = ocrolib.read_text(fname)
        l = list(lstm.normalize_nfkc(transcript))
        charset = charset.union(l)
    charset = sorted(list(charset))
    charset = [c for c in charset if c>" " and c!="~"]
else:
    print("# using default codec")
    charset = sorted(list(set(list(lstm.ascii_labels) + list(ocrolib.chars.default))))

charset = [""," ","~",]+[c for c in charset if c not in [" ","~"]]
print("# charset size", len(charset), end=' ')
if len(charset)<200:
    print("[" + "".join(charset) + "]")
else:
    s = "".join(charset)
    print("[" + s[:20], "...", s[-20:] + "]")
codec = lstm.Codec().init(charset)


# Load an existing network or construct a new one
# Somewhat convoluted logic for dealing with old style Python
# modules and new style C++ LSTM networks.

def save_lstm(fname,network):
    if args.clstm:
        network.lstm.save(fname)
    else:
        if args.strip:
            network.clear_log()
            for x in network.walk(): x.preSave()
        ocrolib.save_object(fname,network)
        if args.strip:
            for x in network.walk(): x.postLoad()


def load_lstm(fname):
    if args.clstm:
        network = lstm.SeqRecognizer(args.height,args.hiddensize,
            codec=codec,
            normalize=lstm.normalize_nfkc)
        import clstm
        mylstm = clstm.make_BIDILSTM()
        mylstm.init(network.No,args.hiddensize,network.Ni)
        mylstm.load(fname)
        network.lstm = clstm.CNetwork(mylstm)
        return network
    else:
        network = ocrolib.load_object(last_save)
        network.upgrade()
        for x in network.walk(): x.postLoad()
        return network

if args.load:
    print("# loading", args.load)
    last_save = args.load
    network = load_lstm(args.load)
else:
    last_save = None
    network = lstm.SeqRecognizer(args.height,args.hiddensize,
        codec=codec,
        normalize=lstm.normalize_nfkc)
    if args.clstm:
        import clstm
        mylstm = clstm.make_BIDILSTM()
        mylstm.init(network.No,args.hiddensize,network.Ni)
        network.lstm = clstm.CNetwork(mylstm)

if getattr(network,"lnorm",None) is None:
    network.lnorm = lnorm

network.upgrade()
if network.last_trial%100==99: network.last_trial += 1
print("# last_trial", network.last_trial)


# set up the learning rate

network.setLearningRate(args.lrate,0.9)
if args.updates: network.lstm.verbose = 1

# used for plotting

plt.ion()
plt.rc('xtick',labelsize=7)
plt.rc('ytick',labelsize=7)
plt.rcParams.update({"font.size":7})


def cleandisp(s):
    return re.sub('[$]',r'#',s)


def plot_network_info(network,transcript,pred,gta):
    plt.subplot(511)
    plt.imshow(line.T,cmap=plt.cm.gray)
    plt.title(cleandisp(transcript))
    plt.subplot(512)
    plt.gca().set_xticks([])
    plt.imshow(network.outputs.T[1:],vmin=0,cmap=plt.cm.hot)
    plt.title(cleandisp(pred[:len(transcript)]))
    plt.subplot(513)
    plt.imshow(network.aligned.T[1:],vmin=0,cmap=plt.cm.hot)
    plt.title(cleandisp(gta[:len(transcript)]))
    plt.subplot(514)
    plt.plot(network.outputs[:,0],color='yellow',linewidth=3,alpha=0.5)
    plt.plot(network.outputs[:,1],color='green',linewidth=3,alpha=0.5)
    plt.plot(np.amax(network.outputs[:,2:],axis=1),color='blue',linewidth=3,alpha=0.5)
    plt.plot(network.aligned[:,0],color='orange',linestyle='dashed',alpha=0.7)
    plt.plot(network.aligned[:,1],color='green',linestyle='dashed',alpha=0.5)
    plt.plot(np.amax(network.aligned[:,2:],axis=1),color='blue',linestyle='dashed',alpha=0.5)
    plt.subplot(515)
    plt.gca().set_yscale('log')
    r = 10000
    errs = network.errors(range=r,smooth=100)
    xs = np.arange(len(errs))+network.last_trial-len(errs)
    plt.plot(xs,errs,color='black')
    plt.plot(xs,network.errors(range=r),color='black',alpha=0.4)
    plt.plot(xs,network.cerrors(range=r,smooth=100),color='red',linestyle='dashed')

start = args.start if args.start>=0 else network.last_trial

for trial in range(start,args.ntrain):
    network.last_trial = trial+1

    do_display = (args.display>0 and trial%args.display==0)
    do_update = 1

    if args.movie and do_display:
        fname = args.moviesample
        do_update = 0
    else:
        fname = pyrandom.sample(inputs,1)[0]

    base,_ = ocrolib.allsplitext(fname)
    try:
        line = ocrolib.read_image_gray(fname)
        transcript = ocrolib.read_text(base+".gt.txt")
    except IOError as e:
        print("ERROR", e)
        continue

    if not args.nolineest:
        assert "dew.png" not in fname,"don't dewarp already dewarped lines"
        network.lnorm.measure(np.amax(line)-line)
        line = network.lnorm.normalize(line,cval=np.amax(line))
    else:
        assert "dew.png" in fname,"input must already be dewarped"

    if line.size<10 or np.amax(line)==np.amin(line):
        print("EMPTY-INPUT")
        continue
    line = line * 1.0/np.amax(line)
    line = np.amax(line)-line
    line = line.T
    if args.pad>0:
        w = line.shape[1]
        line = np.vstack([np.zeros((args.pad,w)),line,np.zeros((args.pad,w))])
    cs = np.array(codec.encode(transcript),'i')
    try:
        pcs = network.trainSequence(line,cs,update=do_update,key=fname)
    except FloatingPointError as e:
        print("# oops, got FloatingPointError", e)
        traceback.print_exc()
        network = load_lstm(last_save)
        continue
    except lstm.RangeError as e:
        continue
    pred = "".join(codec.decode(pcs))
    acs = lstm.translate_back(network.aligned)
    gta = "".join(codec.decode(acs))
    if not args.quiet:
        print("%d %.2f %s" % (trial, network.error, line.shape), fname)
        print("   TRU:", repr(transcript))
        print("   ALN:", repr(gta[:len(transcript)+5]))
        print("   OUT:", repr(pred[:len(transcript)+5]))

    pred = re.sub(' ','_',pred)
    gta = re.sub(' ','_',gta)

    if (trial+1)%args.savefreq==0:
        ofile = oname%(trial+1)+".gz"
        print("# saving", ofile)
        save_lstm(ofile,network)
        last_save = ofile

    if do_display:
        plt.figure("training",figsize=(1400//75,800//75),dpi=75)
        plt.clf()
        plt.gcf().canvas.set_window_title(args.output)
        plot_network_info(network,transcript,pred,gta)
        plt.ginput(1,0.01)
        if args.movie is not None:
            plt.draw()
            plt.savefig("%s-%08d.png"%(args.movie,trial),bbox_inches=0)
