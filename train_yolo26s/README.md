# train_yolo26s

这是 FoodGuard 的 YOLO26-OBB 营养成分表检测实验目录，负责训练、对比实验、ONNX 导出与推理前模型准备。

当前数据集使用 **OBB 旋转框格式**，不是普通 YOLO 水平框格式。标签格式为：

```text
class x1 y1 x2 y2 x3 y3 x4 y4
```

因此训练入口应使用 `yolo26*-obb` 权重或 OBB 结构 YAML。

## 当前文件结构

```text
data/                 原始标注数据与说明（images/labels 不提交）
dataset/              split_dataset.py 生成的训练/验证/测试集
models/               自定义 YOLO26-OBB 模型结构 YAML
runs/                 训练输出（图表、CSV 等结果保留；weights/ 模型文件不提交）
tests/                训练脚本、模型结构与导出测试
ultralytics_ext/      CoordAttention 自定义模块
split_dataset.py      数据集划分脚本
train_yolo26n_obb.py  YOLO26n-OBB 轻量对比训练入口
train_yolo26s_obb.py  YOLO26s-OBB 基线训练入口
train_yolo26s_obb_tuned.py  YOLO26s-OBB 调参训练入口
train_yolo26s_obb_p2.py     P2 高分辨率检测头实验入口
train_yolo26s_obb_coordatt.py       CoordAttention 实验入口
train_yolo26s_obb_rescoordatt_p3.py P3 残差 CoordAttention 实验入口
export_onnx.py        模型 ONNX 导出脚本（支持元数据自动解析、自定义模块注册、FP16）
```

说明：

- 该目录不直接参与 Web 请求处理，线上分析侧实际消费的是导出的 YOLO ONNX 模型。
- 训练结果中的 `results.csv`、曲线图和对比实验记录可直接作为论文实验章节素材。

## PyCharm 运行顺序

### 1. 检查环境

解释器选择 conda 环境 `train_env`，确认已安装：

```text
ultralytics
torch
tensorflow
onnx
onnxruntime-gpu
PyYAML
tqdm
```

CUDA 是否可用由训练脚本自动检测；不可用时会回退到 CPU。

### 2. 准备数据集

如果 `dataset/` 尚未生成，先运行：

```text
split_dataset.py
```

脚本会读取 `data/images`、`data/labels` 和 `data/classes.txt`，只保留 `nutrition_table` 类，并生成：

```text
dataset/dataset.yaml
dataset/images/{train,val,test}
dataset/labels/{train,val,test}
```

### 3. 训练 OBB 基线

优先运行：

```text
train_yolo26s_obb.py
```

默认配置：

```text
model: yolo26s-obb.pt
task: obb
epochs: 180
imgsz: 640
project: runs/train
name: yolo26s-obb-baseline
```

如需更高分辨率调参版本，运行：

```text
train_yolo26s_obb_tuned.py
```

### 4. 运行对比实验

当前已有对比入口：

```text
train_yolo26n_obb.py
train_yolo26s_obb_p2.py
train_yolo26s_obb_coordatt.py
train_yolo26s_obb_rescoordatt_p3.py
```

其中 `coordatt` 与 `rescoordatt_p3` 会使用 `ultralytics_ext/` 中的自定义注意力模块。

## 当前自定义模型

```text
models/yolo26s-obb-p2.yaml
models/yolo26s-obb-coordatt.yaml
models/yolo26s-obb-rescoordatt-p3.yaml
```

这些 YAML 都以单类 `nutrition_table` 为目标，并使用 `OBB26` 检测头。

## 测试

当前 `tests/` 目录包含：

- 训练脚本与模型结构测试：`test_train_yolo26s_obb.py`、`test_coordatt_experiment.py`、`test_lightweight_and_p2_experiments.py`
- ONNX 导出测试：`test_export_onnx.py`（覆盖默认权重路径、元数据解析、CLI 参数、自定义模块注册、输出重命名）

```powershell
python -m unittest tests.test_train_yolo26s_obb tests.test_coordatt_experiment tests.test_lightweight_and_p2_experiments tests.test_export_onnx
```
