# Jupyter测试镜像

这是一个简单的Jupyter测试镜像，用于测试K8s Pod创建和Jupyter连接功能。

## 特点

- **轻量级**: 基于Python 3.11-slim，体积小
- **无需联网**: 构建后可以离线使用
- **预配置**: 已配置Jupyter允许所有IP访问，适合K8s NodePort
- **即用**: 包含示例notebook

## 使用方法

### 方法1: 使用自动化脚本（推荐）

```bash
cd test-images/jupyter-test
chmod +x build_and_import.sh
sudo ./build_and_import.sh
```

脚本会自动：
1. 使用Docker构建镜像
2. 导出为tar文件
3. 导入到K3s的containerd
4. 标记镜像

### 方法2: 手动构建和导入

#### 步骤1: 构建镜像

```bash
cd test-images/jupyter-test
docker build -t jupyter-test:latest .
```

#### 步骤2: 导出镜像

```bash
docker save jupyter-test:latest -o /tmp/jupyter-test.tar
```

#### 步骤3: 导入到K3s

```bash
# 查找K3s的ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

# 导入镜像
sudo $CTR_PATH images import /tmp/jupyter-test.tar

# 标记镜像（可选，但推荐）
sudo $CTR_PATH images tag docker.io/jupyter-test:latest jupyter-test:latest
```

### 方法3: 从其他节点复制

如果控制节点已经构建了镜像：

```bash
# 在控制节点上
docker save jupyter-test:latest -o /tmp/jupyter-test.tar

# 传输到worker节点
scp /tmp/jupyter-test.tar user@worker:/tmp/

# 在worker节点上导入
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
sudo $CTR_PATH images import /tmp/jupyter-test.tar
sudo $CTR_PATH images tag docker.io/jupyter-test:latest jupyter-test:latest
```

## 验证镜像

```bash
# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

# 列出镜像
sudo $CTR_PATH images ls | grep jupyter-test
```

## 在系统中使用

1. **添加到数据库镜像列表**:

   可以通过后端API或直接操作数据库添加镜像：

   ```sql
   INSERT INTO images (name, tag, description, visibility, created_at)
   VALUES ('jupyter-test', 'latest', 'Jupyter测试镜像', 'public', NOW());
   ```

   或者使用Python脚本：

   ```python
   from app.models.image import Image
   from app.core.database import SessionLocal
   
   db = SessionLocal()
   image = Image(
       name="jupyter-test",
       tag="latest",
       description="Jupyter测试镜像",
       visibility="public"
   )
   db.add(image)
   db.commit()
   ```

2. **创建Pod测试**:

   在网页中申请资源时，选择 `jupyter-test:latest` 镜像即可。

## 测试Jupyter连接

1. 创建Pod后，等待Pod状态变为Running
2. 在"我的实例"页面查看Jupyter端口（通常是30000-32767之间的端口）
3. 访问: `http://<节点IP>:<jupyter_port>`
4. 应该能看到Jupyter Lab界面

## 故障排查

### 问题1: 镜像构建失败

**原因**: 网络问题导致无法下载Python包

**解决**: 
- 如果完全离线，需要先在有网络的机器上构建
- 或者修改Dockerfile，使用已下载的wheel文件

### 问题2: 镜像导入失败

**原因**: ctr命令路径不正确或权限不足

**解决**:
```bash
# 确保使用sudo
# 检查ctr路径
sudo find /var/lib/rancher -name ctr

# 使用完整路径导入
sudo /var/lib/rancher/k3s/data/current/bin/ctr images import /tmp/jupyter-test.tar
```

### 问题3: Pod创建后无法访问Jupyter

**检查项**:
1. Pod状态是否为Running: `kubectl get pods`
2. Pod日志: `kubectl logs <pod-name>`
3. Service是否创建: `kubectl get svc`
4. 防火墙是否允许NodePort端口访问

## 镜像信息

- **基础镜像**: python:3.11-slim
- **Jupyter版本**: 最新稳定版
- **端口**: 8888
- **工作目录**: /workspace
- **配置**: 允许所有IP访问，无密码，无token

## 注意事项

1. 此镜像仅用于测试，生产环境请使用更安全的配置
2. 镜像体积约200-300MB（取决于Python包）
3. 如果需要在多节点使用，需要在每个节点导入镜像
4. 或者配置K3s使用私有镜像仓库

