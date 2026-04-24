from __future__ import annotations

import torch
from torch import nn


class CoordAtt(nn.Module):
    """Coordinate attention block that preserves feature-map shape."""

    def __init__(self, channels: int, reduction: int = 32) -> None:
        super().__init__()
        hidden_channels = max(8, channels // reduction)

        self.conv1 = nn.Conv2d(channels, hidden_channels, kernel_size=1, stride=1, padding=0, bias=False)
        self.bn1 = nn.BatchNorm2d(hidden_channels)
        self.act = nn.SiLU(inplace=True)
        self.conv_h = nn.Conv2d(hidden_channels, channels, kernel_size=1, stride=1, padding=0)
        self.conv_w = nn.Conv2d(hidden_channels, channels, kernel_size=1, stride=1, padding=0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x
        _, _, height, width = x.size()

        x_h = x.mean(dim=3, keepdim=True)
        x_w = x.mean(dim=2, keepdim=True).transpose(2, 3)

        y = torch.cat((x_h, x_w), dim=2)
        y = self.act(self.bn1(self.conv1(y)))

        x_h, x_w = torch.split(y, [height, width], dim=2)
        x_w = x_w.transpose(2, 3)

        return identity * self.conv_h(x_h).sigmoid() * self.conv_w(x_w).sigmoid()


class ResidualCoordAtt(nn.Module):
    """Identity-safe residual wrapper around coordinate attention."""

    def __init__(self, channels: int, reduction: int = 32, init_scale: float = 0.0) -> None:
        super().__init__()
        self.attention = CoordAtt(channels, reduction)
        self.scale = nn.Parameter(torch.tensor(float(init_scale)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.scale * self.attention(x)
