# Jupyter 访问故障排查指南

> **问题现象**：Pod 运行成功，但无法访问 JupyterLab

## 快速诊断

运行诊断脚本（在 control 节点）：

```bash
cd /path/to/Computing-Power-Cloud-Platform/backend
python scripts/diagnose_jupyter_access.py <pod_name>
```

例如：

```bash
python scripts/diagnose_jupyter_access.py pod-19-containe
```

## 常见问题及解决方案

### 问题 1：Jupyter 只监听 127.0.0.1:8888（最常见）

**症状**：
- Pod 状态正常（Running）
- Service 已创建
- 但无法访问

**原因**：
Jupyter 默认只监听 `127.0.0.1:8888`，容器外部无法访问。

**验证方法**：

```bash
kubectl exec <pod_name> -n default -- ss -lntp | grep 8888
```

如果看到 `127.0.0.1:8888`，说明问题已确认。

**解决方案**：

#### 方案 A：修改 Dockerfile（推荐，永久修复）

确保 Dockerfile 中的 CMD 包含 `--ip=0.0.0.0`：

```dockerfile
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
```

然后重新构建并导入镜像。

#### 方案 B：临时修复（快速验证）

进入 Pod 并手动启动 Jupyter：

```bash
# 1. 进入 Pod
kubectl exec -it <pod_name> -n default -- bash

# 2. 查看当前 Jupyter 进程（如果有）
ps aux | grep jupyter

# 3. 停止旧进程（如果存在）
pkill -f jupyter

# 4. 使用正确的参数重新启动
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --notebook-dir=/workspace
```

**注意**：Pod 重启后修改会丢失，这是临时方案。

---

### 问题 2：没有 Service 或 Service 未分配 NodePort

**症状**：
- Pod 运行正常
- 但没有对外暴露的端口

**验证方法**：

```bash
# 从 Pod 名称推断 Service 名称
# pod-{id}-{container_id} -> svc-{id}
kubectl get svc -n default | grep svc-

# 查看 Service 详情
kubectl get svc <service_name> -n default -o yaml
```

**解决方案**：

#### 如果 Service 不存在

检查后端日志，看 Service 创建是否失败：

```bash
# 查看后端日志
sudo journalctl -u computing-platform-backend -f
# 或
docker logs <backend_container> -f
```

#### 如果 Service 存在但没有 NodePort

手动创建或重新创建 Service：

```bash
# 删除旧 Service（如果存在）
kubectl delete svc <service_name> -n default

# 重新创建 Pod（会同时创建 Service）
# 在平台前端重新申请资源
```

---

### 问题 3：Service Endpoints 为空

**症状**：
- Service 存在
- 但 Endpoints 为空

**验证方法**：

```bash
kubectl get endpoints <service_name> -n default
```

**原因**：
Pod 标签与 Service selector 不匹配。

**解决方案**：

检查 Pod 标签：

```bash
kubectl get pod <pod_name> -n default --show-labels
```

检查 Service selector：

```bash
kubectl get svc <service_name> -n default -o jsonpath='{.spec.selector}'
```

确保标签匹配（应该都有 `app: pod-{id}-{container_id}`）。

---

### 问题 4：端口被防火墙阻止

**症状**：
- Pod、Service 都正常
- 端口转发可以访问，但 NodePort 不行

**验证方法**：

```bash
# 测试端口转发（绕过防火墙）
kubectl port-forward <pod_name> 8888:8888
# 在另一个终端访问 http://localhost:8888

# 如果端口转发可以，但 NodePort 不行，说明是防火墙问题
```

**解决方案**：

```bash
# Ubuntu/Debian
sudo ufw allow <jupyter_port>/tcp
sudo ufw reload

# CentOS/RHEL
sudo firewall-cmd --add-port=<jupyter_port>/tcp --permanent
sudo firewall-cmd --reload
```

---

### 问题 5：Jupyter 需要 Token 但未配置

**症状**：
- 能打开页面，但要求输入 token 或密码

**解决方案**：

检查 Jupyter 日志获取 token：

```bash
kubectl logs <pod_name> -n default | grep token
```

在 URL 中添加 token：

```
http://<node_ip>:<jupyter_port>/?token=<token>
```

**永久解决**：在 Dockerfile 中禁用 token：

```dockerfile
RUN echo "c.ServerApp.token = ''" >> /root/.jupyter/jupyter_lab_config.py
```

---

## 完整排查流程

### Step 1：检查 Pod 状态

```bash
kubectl get pod <pod_name> -n default
kubectl describe pod <pod_name> -n default
```

**期望结果**：
- Status: Running
- Ready: True
- 有 Pod IP

### Step 2：检查 Jupyter 端口监听

```bash
kubectl exec <pod_name> -n default -- ss -lntp | grep 8888
```

**期望结果**：
- 看到 `0.0.0.0:8888` 或 `*:8888`
- **不是** `127.0.0.1:8888`

### Step 3：检查 Jupyter 日志

```bash
kubectl logs <pod_name> -n default --tail=50
```

**期望看到**：
- `Jupyter Server is running at: http://0.0.0.0:8888/`
- 没有错误信息

### Step 4：检查 Service

```bash
# 获取 Service 名称（从 Pod 名称推断）
ALLOCATION_ID=$(kubectl get pod <pod_name> -n default -o jsonpath='{.metadata.labels.allocation-id}')
SERVICE_NAME="svc-${ALLOCATION_ID}"

# 查看 Service
kubectl get svc ${SERVICE_NAME} -n default -o yaml

# 查看 NodePort
kubectl get svc ${SERVICE_NAME} -n default -o jsonpath='{.spec.ports[?(@.name=="jupyter")].nodePort}'
```

**期望结果**：
- Service 类型是 NodePort
- Jupyter 端口有 NodePort（30000-32767 范围）

### Step 5：检查 Endpoints

```bash
kubectl get endpoints ${SERVICE_NAME} -n default
```

**期望结果**：
- Endpoints 列表中有 Pod IP

### Step 6：获取访问地址

```bash
# 获取节点 IP
NODE_NAME=$(kubectl get pod <pod_name> -n default -o jsonpath='{.spec.nodeName}')
NODE_IP=$(kubectl get node ${NODE_NAME} -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')

# 获取 Jupyter NodePort
JUPYTER_PORT=$(kubectl get svc ${SERVICE_NAME} -n default -o jsonpath='{.spec.ports[?(@.name=="jupyter")].nodePort}')

echo "访问地址: http://${NODE_IP}:${JUPYTER_PORT}"
```

### Step 7：测试访问

#### 方法 A：端口转发（绕过防火墙）

```bash
kubectl port-forward <pod_name> 8888:8888
```

然后在浏览器访问 `http://localhost:8888`

#### 方法 B：直接访问 NodePort

```bash
curl -I http://<node_ip>:<jupyter_port>
```

---

## 快速修复脚本

如果确认是 Jupyter 监听地址问题，可以使用以下脚本临时修复：

```bash
#!/bin/bash
# fix_jupyter_listening.sh

POD_NAME=$1

if [ -z "$POD_NAME" ]; then
    echo "用法: $0 <pod_name>"
    exit 1
fi

echo "修复 Pod ${POD_NAME} 的 Jupyter 监听地址..."

# 进入 Pod 并重启 Jupyter
kubectl exec ${POD_NAME} -n default -- bash -c "
    # 停止现有 Jupyter 进程
    pkill -f jupyter || true
    
    # 等待进程结束
    sleep 2
    
    # 以后台方式启动 Jupyter
    nohup jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --notebook-dir=/workspace > /tmp/jupyter.log 2>&1 &
    
    echo 'Jupyter 已重启，请检查日志:'
    sleep 3
    tail -20 /tmp/jupyter.log
"

echo "✅ 修复完成"
echo "验证: kubectl exec ${POD_NAME} -n default -- ss -lntp | grep 8888"
```

---

## 预防措施

### 1. 确保 Dockerfile 正确配置

```dockerfile
# 配置 Jupyter
RUN echo "c.ServerApp.ip = '0.0.0.0'" >> /root/.jupyter/jupyter_lab_config.py && \
    echo "c.ServerApp.port = 8888" >> /root/.jupyter/jupyter_lab_config.py && \
    echo "c.ServerApp.token = ''" >> /root/.jupyter/jupyter_lab_config.py

# CMD 也要包含 --ip=0.0.0.0
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
```

### 2. 创建 Pod 前验证镜像

```bash
# 构建镜像后验证
docker run --rm -d --name test <image_name>
docker exec test ss -lntp | grep 8888
docker stop test
```

### 3. 添加健康检查

在 Pod 定义中添加 readiness probe：

```yaml
readinessProbe:
  httpGet:
    path: /
    port: 8888
  initialDelaySeconds: 10
  periodSeconds: 5
```

---

## 相关文档

- [K3s镜像使用说明.md](./K3s镜像使用说明.md)
- [故障排查指南.md](./故障排查指南.md)
- [故障复盘-镜像引用名规范化问题.md](./故障复盘-镜像引用名规范化问题.md)

