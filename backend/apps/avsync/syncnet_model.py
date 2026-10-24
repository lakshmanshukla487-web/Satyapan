"""SyncNet (VGG-M variant 'S', Chung & Zisserman) in PyTorch. Layer names match the public `syncnet_v2.model` checkpoint
(keys netcnnaud.*, netfcaud.*, netcnnlip.*, netfclip.*), so the checkpoint loads with strict=True.

LICENCE: the architecture is a published research design; the PRETRAINED WEIGHTS from the University of Oxford (VGG) are
distributed for research use. For a commercial deployment get a licence from the authors or train your own weights with
this architecture before going live. The code in this file is original.
"""
import torch
import torch.nn as nn


class SyncNetS(nn.Module):
    def __init__(self, embed_dim: int = 1024):
        super().__init__()
        self.netcnnaud = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1)), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 1), stride=(1, 1)),
            nn.Conv2d(64, 192, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1)), nn.BatchNorm2d(192), nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(1, 2)),
            nn.Conv2d(192, 384, kernel_size=(3, 3), padding=(1, 1)), nn.BatchNorm2d(384), nn.ReLU(inplace=True),
            nn.Conv2d(384, 256, kernel_size=(3, 3), padding=(1, 1)), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.Conv2d(256, 256, kernel_size=(3, 3), padding=(1, 1)), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(3, 3), stride=(2, 2)),
            nn.Conv2d(256, 512, kernel_size=(5, 4), padding=(0, 0)), nn.BatchNorm2d(512), nn.ReLU(),
        )
        self.netfcaud = nn.Sequential(nn.Linear(512, 512), nn.BatchNorm1d(512), nn.ReLU(), nn.Linear(512, embed_dim))
        self.netfclip = nn.Sequential(nn.Linear(512, 512), nn.BatchNorm1d(512), nn.ReLU(), nn.Linear(512, embed_dim))
        self.netcnnlip = nn.Sequential(
            nn.Conv3d(3, 96, kernel_size=(5, 7, 7), stride=(1, 2, 2), padding=0), nn.BatchNorm3d(96), nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2)),
            nn.Conv3d(96, 256, kernel_size=(1, 5, 5), stride=(1, 2, 2), padding=(0, 1, 1)), nn.BatchNorm3d(256), nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1)),
            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)), nn.BatchNorm3d(256), nn.ReLU(inplace=True),
            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)), nn.BatchNorm3d(256), nn.ReLU(inplace=True),
            nn.Conv3d(256, 256, kernel_size=(1, 3, 3), padding=(0, 1, 1)), nn.BatchNorm3d(256), nn.ReLU(inplace=True),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 2, 2)),
            nn.Conv3d(256, 512, kernel_size=(1, 6, 6), padding=0), nn.BatchNorm3d(512), nn.ReLU(inplace=True),
        )

    def forward_aud(self, x: torch.Tensor) -> torch.Tensor:  # x: N x 1 x 13 x 20 (MFCC)
        mid = self.netcnnaud(x)
        return self.netfcaud(mid.reshape(mid.size(0), -1))

    def forward_lip(self, x: torch.Tensor) -> torch.Tensor:  # x: N x 3 x 5 x 224 x 224 (BGR, 0..255)
        mid = self.netcnnlip(x)
        return self.netfclip(mid.reshape(mid.size(0), -1))
