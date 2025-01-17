#    Copyright (C) 2018 Ruotian Luo, Toyota Technological Institute at Chicago

import numpy as np

import torch.nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

import torch
import torch.nn as nn


def norm_log_liklihood(x, mu, logvar):
    return -0.5 * torch.sum(logvar + np.log(2 * np.pi) +
                            torch.div(torch.pow((x - mu), 2), torch.exp(logvar)), 1)


def sample_gaussian(mu, logvar):
    epsilon = logvar.new_empty(logvar.size()).normal_()
    std = torch.exp(0.5 * logvar)
    z = mu + std * epsilon
    return z


def dynamic_rnn(cell, inputs, sequence_length, max_len, init_state=None, output_fn=None):
    sorted_lens, len_ix = sequence_length.sort(0, descending=True)

    # Used for later reorder
    inv_ix = len_ix.clone()
    inv_ix[len_ix] = torch.arange(0, len(len_ix)).type_as(inv_ix)

    # The number of inputs that have lengths > 0
    valid_num = torch.sign(sorted_lens).long().sum().item()
    zero_num = inputs.size(0) - valid_num

    sorted_inputs = inputs[len_ix].contiguous()
    if init_state is not None:
        sorted_init_state = init_state[:, len_ix].contiguous()

    packed_inputs = pack_padded_sequence(sorted_inputs[:valid_num], list(sorted_lens[:valid_num]),
                                         batch_first=True)

    if init_state is not None:
        outputs, state = cell(packed_inputs, sorted_init_state[:, :valid_num])
    else:
        outputs, state = cell(packed_inputs)

    # Reshape *final* output to (batch_size, hidden_size)
    outputs, _ = pad_packed_sequence(outputs, batch_first=True, total_length=max_len)

    # Add back the zero lengths
    if zero_num > 0:
        outputs = torch.cat(
            [outputs, outputs.new_zeros(zero_num, outputs.size(1), outputs.size(2))], 0)
        if init_state is not None:
            state = torch.cat([state, sorted_init_state[:, valid_num:]], 1)
        else:
            state = torch.cat([state, state.new_zeros(state.size(0), zero_num, state.size(2))], 1)

    # Reorder to the original order
    new_outputs = outputs[inv_ix].contiguous()
    new_state = state[:, inv_ix].contiguous()

    # compensate the last last layer dropout, necessary????????? need to check!!!!!!!!
    new_new_state = F.dropout(new_state, cell.dropout, cell.training)
    new_new_outputs = F.dropout(new_outputs, cell.dropout, cell.training)

    if output_fn is not None:
        new_new_outputs = output_fn(new_new_outputs)

    return new_new_outputs, new_new_state


def get_bow(embedding, avg=False):
    """
    Assumption, the last dimension is the embedding
    The second last dimension is the sentence length. The rank must be 3
    """
    embedding_size = embedding.size(2)
    if avg:
        return embedding.mean(1), embedding_size
    else:
        return embedding.sum(1), embedding_size


def get_rnn_encode(embedding, cell, length_mask=None):
    """
    Assumption, the last dimension is the embedding
    The second last dimension is the sentence length. The rank must be 3
    The padding should have zero
    """
    if length_mask is None:
        length_mask = torch.sum(torch.sign(torch.max(torch.abs(embedding), 2)[0]), 1)
        length_mask = length_mask.long()
    _, encoded_input = dynamic_rnn(cell, embedding, sequence_length=length_mask)

    # get only the last layer
    encoded_input = encoded_input[-1]
    return encoded_input, cell.hidden_size


def get_bi_rnn_encode(embedding, cell, max_len, length_mask=None):
    """
    Assumption, the last dimension is the embedding
    The second last dimension is the sentence length. The rank must be 3
    The padding should have zero
    """
    if length_mask is None:
        length_mask = torch.sum(torch.sign(torch.max(torch.abs(embedding), 2)[0]), 1)
        length_mask = length_mask.long()
    _, encoded_input = dynamic_rnn(cell, embedding, sequence_length=length_mask, max_len=max_len)
    # get only the last layer
    encoded_input2 = torch.cat([encoded_input[-2], encoded_input[-1]], 1)
    return encoded_input2, cell.hidden_size * 2


def get_rnncell(cell_type, input_size, cell_size, keep_prob, num_layer, bidirectional=False):
    if cell_type == 'gru':
        cell = nn.GRU(input_size, cell_size, num_layers=num_layer, dropout=1 - keep_prob,
                      bidirectional=bidirectional, batch_first=True)
    elif cell_type == 'lstm':
        cell = nn.LSTM(input_size, cell_size, num_layers=num_layer, dropout=1 - keep_prob,
                       bidirectional=bidirectional, batch_first=True)
    else:
        raise ValueError("Set cell type RNN: 'gru' or 'lstm'")
    return cell