# Jupyter测试镜像 - 快速开始

## 快速步骤

### 1. 构建和导入镜像

#### 情况A: 有Docker或nerdctl

在Linux服务器上（有Docker/nerdctl和K3s的节点）：

```bash
cd test-images/jupyter-test
chmod +x build_and_import.sh
sudo ./build_and_import.sh
```

#### 情况B: 只有K3s containerd（无Docker）

**推荐方法：从其他机器构建并导入**

1. **在有Docker的机器上构建**：
```bash
cd test-images/jupyter-test
docker build -t jupyter-test:latest .
docker save jupyter-test:latest -o jupyter-test.tar
```

2. **传输到K3s服务器**：
```bash
scp jupyter-test.tar control@<k3s-server>:/tmp/
```

3. **在K3s服务器上导入**：
```bash
cd test-images/jupyter-test
chmod +x import_from_tar.sh
sudo ./import_from_tar.sh /tmp/jupyter-test.tar
```

**或者安装nerdctl**（推荐用于长期使用）：
```bash
# 下载并安装nerdctl
wget https://github.com/containerd/nerdctl/releases/download/v1.5.0/nerdctl-1.5.0-linux-amd64.tar.gz
tar -xzf nerdctl-1.5.0-linux-amd64.tar.gz
sudo mv nerdctl /usr/local/bin/
sudo chmod +x /usr/local/bin/nerdctl

# 然后使用nerdctl构建
cd test-images/jupyter-test
sudo nerdctl build -t jupyter-test:latest .
```

详细说明请查看 [离线导入说明.md](离线导入说明.md)

### 2. 添加到数据库

```bash
cd backend
python ../test-images/jupyter-test/add_to_database.py
```

或者手动添加到数据库：

```sql
INSERT INTO images (name, tag, description, visibility, created_at)
VALUES ('jupyter-test', 'latest', 'Jupyter测试镜像', 'public', NOW());
```

### 3. 测试创建Pod

1. 在网页中申请资源
2. 选择镜像: `jupyter-test:latest`
3. 选择资源池和GPU数量
4. 提交申请

### 4. 访问Jupyter

1. 等待Pod状态变为Running
2. 在"我的实例"页面查看Jupyter端口
3. 访问: `http://<节点IP>:<jupyter_port>`

## 如果镜像构建失败（离线环境或只有containerd）

### 方法1: 从其他机器构建并导入（推荐）

```bash
# 在有Docker的机器上
cd test-images/jupyter-test
docker build -t jupyter-test:latest .
docker save jupyter-test:latest -o jupyter-test.tar

# 传输到目标服务器
scp jupyter-test.tar user@target-server:/tmp/

# 在目标服务器上导入（使用提供的脚本）
cd test-images/jupyter-test
chmod +x import_from_tar.sh
sudo ./import_from_tar.sh /tmp/jupyter-test.tar
```

### 方法2: 安装nerdctl

```bash
# 下载nerdctl
wget https://github.com/containerd/nerdctl/releases/download/v1.5.0/nerdctl-1.5.0-linux-amd64.tar.gz
tar -xzf nerdctl-1.5.0-linux-amd64.tar.gz
sudo mv nerdctl /usr/local/bin/
sudo chmod +x /usr/local/bin/nerdctl

# 使用nerdctl构建
cd test-images/jupyter-test
sudo nerdctl build -t jupyter-test:latest .
```

### 方法2: 使用更小的基础镜像

如果Python镜像太大，可以修改Dockerfile使用alpine版本：

```dockerfile
FROM python:3.11-alpine
# ... 其他配置相同
```

## 验证

```bash
# 检查镜像是否导入
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
sudo $CTR_PATH images ls | grep jupyter-test

# 检查Pod状态
kubectl get pods

# 查看Pod日志
kubectl logs <pod-name>
```

## 常见问题

**Q: Pod创建后一直Pending？**
A: 检查镜像是否已导入: `sudo ctr images ls | grep jupyter-test`

**Q: Jupyter无法访问？**
A: 
1. 检查Pod日志: `kubectl logs <pod-name>`
2. 检查Service: `kubectl get svc`
3. 检查防火墙是否允许NodePort端口

**Q: 镜像导入失败？**
A: 确保使用sudo权限，并检查ctr路径是否正确

