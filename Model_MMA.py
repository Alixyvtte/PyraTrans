import torch
import torch.nn as nn
from pytorch_pretrained_bert import BertModel, BertTokenizer, BertConfig, BertAdam
from Multiple_attention import TAMM
import torch.nn.functional as F
from Model_CharBERT import CharBERTModel
from data_processing import CharbertInput

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class CharBertModel(nn.Module):
    """
    Definition of the CharBertModel we defined to classify Malicious URLs
    """

    def __init__(self):
        super(CharBertModel, self).__init__()
        self.bert = CharBERTModel.from_pretrained('charbert-bert-wiki')
        for param in self.bert.parameters():
            param.requires_grad = True
        self.dropout = nn.Dropout(p=0.1)  # Add a dropout layer
        self.fc = nn.Linear(768, 2)
        self.hidden_size = 768
        self.fuse = nn.Conv1d(2 * self.hidden_size, self.hidden_size, kernel_size=1)

    def forward(self, x):
        context = x[0]
        types = x[1]
        mask = x[2]

        # add char level information
        char_ids = []
        start_ids = []
        end_ids = []
        char_ids, start_ids, end_ids = CharbertInput(context, char_ids, start_ids, end_ids)

        # CharBERTModel return outputs as a tuple
        # outputs =
        # (sequence_output, pooled_output, char_sequence_output, char_pooled_output) + char_encoder_outputs[1:]
        # we need to fuse the sequence_output and char_sequence_output from all hidden layers
        outputs = self.bert(char_input_ids=char_ids, start_ids=start_ids, end_ids=end_ids, input_ids=context,
                            attention_mask=mask,
                            token_type_ids=types, output_hidden_states=True)

        # (pooled_output, char_pooled_output)
        pooled = (outputs[1], outputs[3])

        #  Encoder returns:
        #  last-layer hidden state, (all hidden states_word), (all_hidden_states_char), (all attentions)
        #  tuple(torch.Size([16, 200, 768]),...)
        sequence_repr = outputs[2]
        char_sequence_repr = outputs[3]
        # fuse two channel
        fuse_output =()
        for x1, x2 in zip(sequence_repr, char_sequence_repr):
            x = torch.cat([x1, x2], dim=-1)
            # x torch.Size([16, 200, 768*2])
            x = x.transpose(1, 2)
            # x torch.Size([16, 768*2, 200])
            y = self.fuse(x)
            # y torch.Size([16, 768, 200])
            y = y.transpose(1, 2)
            # y torch.Size([16, 200, 768])
            fuse_output += (y,)

        pyramid = tuple(fuse_output)
        pyramid = torch.stack(pyramid, dim=0).permute(1, 0, 2, 3)
        # torch.Size([16, 12, 200, 768])

        model_tamm = TAMM(channel=12).to(DEVICE)
        pos_pooled = model_tamm.forward(pyramid)
        # torch.Size([16, 12, 200, 768])

        # Finally, the compressed feature has a size of torch.Size([16, 768]).
        compressed_feature_tensor = torch.mean(pos_pooled, dim=2)
        compressed_feature_tensor = torch.mean(compressed_feature_tensor, dim=1)

        out = self.dropout(compressed_feature_tensor)
        out = self.fc(out)

        return pyramid, pooled, out


class Model(nn.Module):
    """
    Definition of the Basic Model we defined to classify Malicious URLs
    """

    def __init__(self):
        super(Model, self).__init__()
        self.bert = BertModel.from_pretrained("charbert-bert-wiki")
        for param in self.bert.parameters():
            param.requires_grad = True
        self.dropout = nn.Dropout(p=0.1)  # Add a dropout layer
        self.fc = nn.Linear(768, 2)

    def forward(self, x):
        context = x[0]
        types = x[1]
        mask = x[2]

        # BertModel return encoded_layers, pooled_output
        # output_all_encoded_layers=True
        outputs, pooled = self.bert(input_ids=context, token_type_ids=types,
                                    attention_mask=mask,
                                    output_all_encoded_layers=True)

        pyramid = tuple(outputs)
        pyramid = torch.stack(pyramid, dim=0).permute(1, 0, 2, 3)
        # torch.Size([16, 12, 200, 768])

        model_tamm = TAMM(channel=12).to(DEVICE)
        pos_pooled = model_tamm.forward(pyramid)
        # torch.Size([16, 12, 200, 768])

        # Finally, the compressed feature has a size of torch.Size([16, 768]).
        compressed_feature_tensor = torch.mean(pos_pooled, dim=2)
        compressed_feature_tensor = torch.mean(compressed_feature_tensor, dim=1)

        out = self.dropout(compressed_feature_tensor)
        out = self.fc(out)

        return pyramid, pooled, out
