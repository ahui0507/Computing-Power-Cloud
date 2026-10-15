# K3s 本地镜像使用说明

## 问题背景

在 K3s 中使用本地导入的镜像时，即使设置了 `imagePullPolicy: IfNotPresent`，K3s/containerd 仍然可能尝试从 Docker Hub 拉取镜像，导致：
- 网络超时
- Pod 状态为 `ImagePullBackOff`
- 无法使用本地镜像

## 解决方案

### 方案1：使用 `imagePullPolicy: Never`（已实现）

代码已修改为使用 `Never` 策略，这样：
- ✅ 完全避免网络拉取
- ✅ 直接使用本地镜像
- ⚠️ 如果镜像不存在，Pod 会直接失败（这是预期的）

### 方案2：重启 K3s 服务

如果仍然遇到问题，可以重启 K3s 服务刷新 containerd 缓存：

```bash
sudo systemctl restart k3s
# 等待10-20秒让服务完全启动
sleep 15
```

### 方案3：确保镜像标签正确

确保镜像有正确的标签：

```bash
# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

# 检查镜像
sudo $CTR_PATH images ls | grep jupyter-test

# 确保有 jupyter-test:latest 标签
sudo $CTR_PATH images tag docker.io/library/jupyter-test:latest jupyter-test:latest
```

### 方案4：使用完整镜像名称

如果短名称不工作，可以在数据库中修改镜像名称使用完整格式：
- `docker.io/library/jupyter-test:latest`
- 或 `docker.io/jupyter-test:latest`

## 验证步骤

1. **检查镜像已导入**：
   ```bash
   CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
   sudo $CTR_PATH images ls | grep jupyter-test
   ```

2. **删除旧 Pod**：
   ```bash
   kubectl delete pod <pod-name> -n default
   ```

3. **重新申请资源**（在网页中）

4. **检查新 Pod**：
   ```bash
   python backend/scripts/check_pod_image_policy.py <new-pod-name>
   ```

5. **验证 Pod 状态**：
   ```bash
   kubectl get pod <pod-name> -n default
   kubectl describe pod <pod-name> -n default
   ```

## 常见问题

### Q: Pod 仍然显示 ImagePullBackOff？

**A:** 可能原因：
1. 后端服务未重启，仍在使用旧代码
2. 镜像标签不匹配
3. 需要重启 K3s 服务

**解决方案**：
```bash
# 1. 重启后端服务
sudo systemctl restart computing-platform-backend
# 或重启运行后端的进程

# 2. 重启 K3s
sudo systemctl restart k3s

# 3. 删除 Pod 并重新创建
kubectl delete pod <pod-name> -n default
```

### Q: 使用 `Never` 策略后，如果镜像不存在会怎样？

**A:** Pod 会直接失败，状态为 `ErrImageNeverPull`。这是预期的行为，因为：
- 镜像应该已经导入
- 如果镜像不存在，应该先导入镜像，而不是尝试拉取

### Q: 多节点集群怎么办？

**A:** 需要在每个节点上都导入镜像：

```bash
# 在每个节点上运行
cd test-images/jupyter-test
sudo ./build_and_import.sh
```

或者配置 K3s 使用私有镜像仓库统一管理镜像。

## 最佳实践

1. **导入镜像后立即验证**：
   ```bash
   CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
   sudo $CTR_PATH images ls | grep <image-name>
   ```

2. **使用明确的镜像标签**：
   - 避免使用 `latest`（如果可能）
   - 使用版本号标签，如 `jupyter-test:v1.0`

3. **在导入脚本中自动添加标签**：
   ```bash
   sudo $CTR_PATH images tag docker.io/library/jupyter-test:latest jupyter-test:latest
   ```

4. **监控 Pod 状态**：
   ```bash
   kubectl get pods -n default -w
   ```

