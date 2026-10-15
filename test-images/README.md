# 测试镜像

这个目录包含用于测试的Docker镜像，特别是用于测试Pod创建和Jupyter连接功能。

## 可用镜像

### jupyter-test

一个简单的Jupyter测试镜像，用于测试：
- Pod创建功能
- Jupyter连接功能
- NodePort Service端口映射

**特点**:
- 基于Python 3.11-slim，体积小（约200-300MB）
- 预配置Jupyter Lab，允许所有IP访问
- 无需密码和token（仅用于测试）
- 包含示例notebook

**使用方法**: 查看 [jupyter-test/README.md](jupyter-test/README.md) 和 [jupyter-test/QUICK_START.md](jupyter-test/QUICK_START.md)

## 添加新测试镜像

1. 在 `test-images/` 下创建新目录
2. 添加 `Dockerfile`
3. 添加 `build_and_import.sh` 脚本
4. 添加 `README.md` 说明文档
5. 可选：添加 `add_to_database.py` 脚本

## 注意事项

- 测试镜像仅用于开发和测试环境
- 生产环境请使用更安全的配置（密码、token等）
- 确保镜像已导入到所有K3s节点
- 或者配置K3s使用私有镜像仓库

