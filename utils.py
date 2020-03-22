from __future__ import division, print_function

import itertools
import os
import pickle
import re

import matplotlib
import numpy as np
np.random.seed(1)
import torch

from conllu import parse, parse_tree
from tags import Tags

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # isort:skip
from collections import defaultdict

FROZEN_TAG = "__frozen__"


def freeze_dict(obj):
    if isinstance(obj, dict):
        dict_items = list(obj.items())
        dict_items.append((FROZEN_TAG, True))
        return tuple([(k, freeze_dict(v)) for k, v in dict_items])
    return obj


def unfreeze_dict(obj):
    if isinstance(obj, tuple):
        if (FROZEN_TAG, True) in obj:
            out = dict((k, unfreeze_dict(v)) for k, v in obj)
            del out[FROZEN_TAG]
            return out
    return obj


def get_lang_code_dicts():
    """
   Returns lang_to_code, code_to_lang dictionaries

  """
    lang_to_code = {}
    code_to_lang = {}
    bad_chars = ",''"
    rgx = re.compile("[%s]" % bad_chars)

    with open("data/lang_codes.txt") as f:
        data = f.read()
        lines = data.split("\n")
        split_line = [line.split() for line in lines]
        for line in split_line[:-2]:
            lang = rgx.sub("", line[0])
            code = rgx.sub("", line[2])
            lang_to_code[lang] = code
        code_to_lang = {v: k for k, v in lang_to_code.items()}
    return lang_to_code, code_to_lang


def read_conll(
    treebank_path, langs, code_to_lang, train_or_dev, tgt_size=None, test=False
):

    """
   Reads conll formatted file

   langs: list of languages
   train: read training data
   returns: dict with data for each language
   as list of tuples of sentences and morph-tags
  """

    annot_sents = {}
    unique = []
    for lang in langs:

        train = train_or_dev if not test else "test"

        if not test:
            for file in os.listdir(treebank_path + "UD_" + code_to_lang[lang]):
                if file.endswith("train.conllu"):
                    filepath = os.path.join(
                        treebank_path + "UD_" + code_to_lang[lang], file
                    )
                    break
        else:
            for file in os.listdir(treebank_path + "UD_" + code_to_lang[lang]):
                if file.endswith("dev.conllu"):
                    filepath = os.path.join(
                        treebank_path + "UD_" + code_to_lang[lang], file
                    )
                    break

        with open(filepath) as f:
            data = f.readlines()[:-1]
            data = [line for line in data if line[0] != "#"]
            split_data = " ".join(data).split("\n \n")
            ud = [parse(sent)[0] for sent in split_data]

            all_text = []
            all_tags = []
            if langs[-1] == lang and tgt_size:
                tgt_size = min(tgt_size, len(ud))
                ud = ud[:tgt_size]
            for sent in ud:
                sent_text = []
                sent_tags = []
                for word in sent:
                    word_tags = {}
                    if word["feats"]:
                        word_tags = dict(word["feats"])
                    if word["upostag"]:
                        if word_tags:
                            word_tags.update({"POS": word["upostag"]})
                        else:
                            word_tags = {"POS": word["upostag"]}

                    if word_tags:
                        word_tags = freeze_dict(word_tags)
                        if word_tags not in unique:
                            unique.append(word_tags)

                    sent_text.append(word["form"])
                    sent_tags.append(freeze_dict(word_tags))

                all_text.append(sent_text)
                all_tags.append(sent_tags)

            annot_sents[lang] = [(w, m) for w, m in zip(all_text, all_tags)]

    return annot_sents, unique


def addNullLabels(annot_sents, langs, unique_tags):

    for lang in langs:
        i = 0
        for w, m in annot_sents[lang]:
            new_tags = []
            for tags in m:
                tag_dict = unfreeze_dict(tags)
                for tag in unique_tags:
                    if tag.name not in tag_dict:
                        tag_dict[tag.name] = "NULL"
                new_tags.append(freeze_dict(tag_dict))

            annot_sents[lang][i] = (w, new_tags)
            i += 1

    return annot_sents


def sortbylength(data, lang_ids, maxlen=500):
    """
  :param data: List of tuples of source sentences and morph tags
  :param lang_ids: List of lang IDs for each sentence
  :param maxlen: Maximum sentence length permitted
  :return: Sorted data and sorted langIDs
  """
    src = [elem[0] for elem in data]
    tgt = [elem[1] for elem in data]
    indexed_src = [(i, src[i]) for i in range(len(src))]
    sorted_indexed_src = sorted(indexed_src, key=lambda x: -len(x[1]))
    sorted_src = [item[1] for item in sorted_indexed_src if len(item[1]) < maxlen]
    sort_order = [item[0] for item in sorted_indexed_src if len(item[1]) < maxlen]
    sorted_tgt = [tgt[i] for i in sort_order]
    sorted_lang_ids = [lang_ids[i] for i in sort_order]
    sorted_data = [(src, tgt) for src, tgt in zip(sorted_src, sorted_tgt)]

    return sorted_data, sorted_lang_ids


def get_train_order(training_data, batch_size, startIdx=0):
    """
  :param data: List of tuples of source sentences and morph tags
  :return: start idxs of batches
  """

    lengths = [len(elem[0]) for elem in training_data]
    start_idxs = []
    end_idxs = []
    prev_length = -1
    batch_counter = 0

    for i, length in enumerate(lengths, start=startIdx):

        if length != prev_length or batch_counter > batch_size:
            start_idxs.append(i)
            if prev_length != -1:
                end_idxs.append(i - 1)
            batch_counter = 1

        batch_counter += 1
        prev_length = length

    end_idxs.append(startIdx + len(lengths) - 1)

    return [(s, e) for s, e in zip(start_idxs, end_idxs)]


def find_unique_tags(train_data_tags, null_label=False):

    unique_tags = Tags()

    for tags in train_data_tags:
        for tag, label in unfreeze_dict(tags).items():
            if not unique_tags.tagExists(tag):
                unique_tags.addTag(tag)

            curTag = unique_tags.getTagbyName(tag)

            if not curTag.labelExists(label):
                curTag.addLabel(label)

    # Add null labels to unseen tags in each tag set
    if null_label:
        for tag in unique_tags:
            tag.addLabel("NULL")

    return unique_tags


def plot_heatmap(uniqueTags, weights, kind):

    font = {"family": "normal", "size": 14, "weight": "bold"}

    matplotlib.rc("font", **font)

    pairs = list(itertools.combinations(range(uniqueTags.size()), 2))

    # weights is a ParameterList
    for k, weight in enumerate(weights):
        if kind == "pair":
            i, j = pairs[k]
            tag1 = uniqueTags.getTagbyIdx(i)
            tag2 = uniqueTags.getTagbyIdx(j)
            tag1_labels = [label.name for label in tag1.labels]
            tag2_labels = [label.name for label in tag2.labels]

            plt.figure(figsize=(20, 18), dpi=80)
            plt.xticks(range(0, len(tag2_labels)), tag2_labels)
            plt.yticks(range(0, len(tag1_labels)), tag1_labels)
            plt.tick_params(labelsize=25)
            plt.xlabel(tag2.name, fontsize=40)
            plt.ylabel(tag1.name, fontsize=50)
            plt.imshow(weight.cpu().numpy(), cmap="Reds", interpolation="nearest")
            plt.savefig(
                "figures/" + tag1.name + "_" + tag2.name + ".png", bbox_inches="tight"
            )
            plt.close()

        elif kind == "trans":
            tag = uniqueTags.getTagbyIdx(k)
            tag_labels = [label.name for label in tag.labels]

            plt.figure(figsize=(20, 18), dpi=80)
            plt.xticks(range(0, len(tag_labels)), tag_labels, rotation=45)
            plt.yticks(range(0, len(tag_labels)), tag_labels)
            plt.tick_params(labelsize=40)
            plt.xlabel(tag.name, fontsize=50)
            plt.ylabel(tag.name, fontsize=50)
            plt.imshow(weight.cpu().numpy(), cmap="Greys", interpolation="nearest")
            plt.savefig(
                "figures/" + tag.name + "_" + tag.name + ".png", bbox_inches="tight"
            )
            plt.close()


def get_var(x, gpu=False, volatile=False):
    if gpu:
        x = x.cuda()
    return x


def prepare_sequence(seq, to_ix, gpu=False):
    if isinstance(to_ix, dict):
        idxs = [to_ix[w] if w in to_ix else to_ix["UNK"] for w in seq]
    elif isinstance(to_ix, list):
        idxs = [to_ix.index(w) if w in to_ix else to_ix.index("UNK") for w in seq]
    tensor = torch.LongTensor(idxs)
    return get_var(tensor, gpu)


def to_scalar(var):
    # returns a python float
    return var.cpu().item()


def argmax(vec):
    # return the argmax as a python int
    _, idx = torch.max(vec, 1)
    return to_scalar(idx)


def logSumExp(a, b):
    maxi = np.maximum(a, b)
    aexp = a - maxi
    bexp = b - maxi
    sumOfExp = np.exp(aexp) + np.exp(bexp)
    return maxi + np.log(sumOfExp)


def logSumExpTensor(vec):
    # vec -> 16, tag_size
    batch_size = vec.size()[0]
    vec = vec.view(batch_size, -1)
    max_score = torch.max(vec, 1)[0]
    max_score_broadcast = max_score.view(-1, 1).expand(-1, vec.size()[1])
    return max_score + torch.log(torch.sum(torch.exp(vec - max_score_broadcast), 1))


def logSumExpTensors(a, b):

    maxi = torch.max(a, b)
    aexp = a - maxi
    bexp = b - maxi
    sumOfExp = torch.exp(aexp) + torch.exp(bexp)
    return maxi + torch.log(sumOfExp)


def logDot(a, b, redAxis=None):

    if redAxis == 1:
        b = b.transpose()

    max_a = np.amax(a)
    max_b = np.amax(b)

    C = np.dot(np.exp(a - max_a), np.exp(b - max_b))
    np.log(C, out=C)
    # else:
    #   np.log(C + 1e-300, out=C)

    C += max_a + max_b

    return C.transpose() if redAxis == 1 else C


def logMax(a, b, redAxis=None):

    if redAxis == 1:
        b = b.transpose()

    max_a = np.amax(a)
    max_b = np.amax(b)

    C = np.max(np.exp(a[:, :, None] - max_a) * np.exp(b[None, :, :] - max_b), axis=1)

    # if np.isfinite(C).all():
    np.log(C, out=C)
    # else:
    #   np.log(C + 1e-300, out=C)

    C += max_a + max_b

    return C.transpose() if redAxis == 1 else C


def logNormalize(a):

    denom = np.logaddexp.reduce(a, 1)
    return (a.transpose() - denom).transpose()


def logNormalizeTensor(a):

    denom = logSumExpTensor(a)
    if len(a.size()) == 2:
        denom = denom.view(-1, 1).expand(-1, a.size()[1])
    elif len(a.size()) == 3:
        denom = denom.view(a.size()[0], 1, 1).expand(-1, a.size()[1], a.size()[2])

    return a - denom


def computeF1(
    hyps, golds, prefix, baseline=False, write_results=False
):
    """
  hyps: List of dicts for predicted morphological tags
  golds: List of dicts for gold morphological tags
  """

    f1_precision_scores = {}
    f1_precision_total = {}
    f1_recall_scores = {}
    f1_recall_total = {}
    f1_average = 0.0

    if baseline:
        hyps = [unfreeze_dict(h) for h in hyps]
        golds = [unfreeze_dict(t) for t in golds]

    # calculate precision
    for i, word_tags in enumerate(hyps, start=0):
        for k, v in word_tags.items():
            if v == "NULL":
                continue
            if k not in f1_precision_scores:
                f1_precision_scores[k] = 0
                f1_precision_total[k] = 0
            if k in golds[i]:
                if v == golds[i][k]:
                    f1_precision_scores[k] += 1
            f1_precision_total[k] += 1

    f1_micro_precision = sum(f1_precision_scores.values()) / sum(
        f1_precision_total.values()
    )

    for k in f1_precision_scores.keys():
        f1_precision_scores[k] = f1_precision_scores[k] / f1_precision_total[k]

    # calculate recall
    for i, word_tags in enumerate(golds, start=0):
        for k, v in word_tags.items():
            if v == "_":
                continue
            if k not in f1_recall_scores:
                f1_recall_scores[k] = 0
                f1_recall_total[k] = 0
            if k in hyps[i]:
                if v == hyps[i][k]:
                    f1_recall_scores[k] += 1
            f1_recall_total[k] += 1

    f1_micro_recall = sum(f1_recall_scores.values()) / sum(f1_recall_total.values())

    f1_scores = {}
    for k in f1_recall_scores.keys():
        f1_recall_scores[k] = f1_recall_scores[k] / f1_recall_total[k]

        if f1_recall_scores[k] == 0 or k not in f1_precision_scores:
            f1_scores[k] = 0
        else:
            f1_scores[k] = (
                2
                * (f1_precision_scores[k] * f1_recall_scores[k])
                / (f1_precision_scores[k] + f1_recall_scores[k])
            )

        f1_average += f1_recall_total[k] * f1_scores[k]

    f1_average /= sum(f1_recall_total.values())
    f1_micro_score = (
        2
        * (f1_micro_precision * f1_micro_recall)
        / (f1_micro_precision + f1_micro_recall)
    )

    if write_results:
        print("Writing F1 scores...")
        with open(prefix + "_results_f1.txt", "a") as file:
            file.write("\nMacro-averaged F1 Score: " + str(f1_average))
            file.write("\nMicro-averaged F1 Score: " + str(f1_micro_score))

    return f1_average, f1_micro_score


def getCorrectCount(golds, hyps):

    correct = 0

    for i, word_tags in enumerate(golds, start=0):
        allCorrect = True
        for k, v in word_tags.items():
            if k in hyps[i]:
                if v != hyps[i][k]:
                    allCorrect = False
                    break

        if allCorrect == True:
            correct += 1

    return correct


def make_bucket_batches(data_collections, feature_wise_tgt_tags, batch_size, shuffle=True):
    # Data are bucketed according to the length of the first item in the data_collections.
    buckets = defaultdict(list)
    data_collections = list(data_collections)
    tot_items = len(data_collections[0])
    for data_item in data_collections:
        src = data_item[0]
        buckets[len(src)].append(data_item)

    batches = []
    # np.random.seed(2)
    for src_len in buckets:
        bucket = buckets[src_len]
        if shuffle:
            np.random.shuffle(bucket)

        num_batches = int(np.ceil(len(bucket) * 1.0 / batch_size))
        for i in range(num_batches):
            cur_batch_size = batch_size if i < num_batches - 1 else len(bucket) - batch_size * i
            batch = [[bucket[i * batch_size + j][k] for j in range(cur_batch_size)] for k in range(tot_items)]

            if feature_wise_tgt_tags is not None:
                batch_tgt_tags = defaultdict(list)
                #batch_known_tgt_tags = defaultdict(list)
                for feat, all_tgt_tags in feature_wise_tgt_tags.items():
                    for sent_index in batch[-1]:
                        batch_tgt_tags[feat].append(all_tgt_tags[sent_index])

                batch.append(batch_tgt_tags)
                #batch.append(batch_known_tgt_tags)


            batches.append(batch)

    if shuffle:
        np.random.shuffle(batches)
    return batches