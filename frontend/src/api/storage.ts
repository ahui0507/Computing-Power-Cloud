import request from '@/utils/request'
import type { FileItem, ApiResponse } from '@/types'

export interface StorageUsage {
  quota_mode?: 'fixed' | 'percent'
  used_bytes?: number | null
  limit_bytes?: number | null
  enforcement: 'filesystem' | 'disabled'
  used_percent: number | null
  share_percent: number
  warning: 'none' | 'low' | 'full'
}
export interface TrainingExampleResult {
  folder: string
  single_command: string
  multi_command: string
}

export const storageApi = {
  usage: () =>
    request.get<ApiResponse<StorageUsage>>('/storage/usage', {
      silentError: true,
    }),
  trainingExample: () =>
    request.post<ApiResponse<TrainingExampleResult>>(
      '/storage/examples/training',
    ),
  // 上传文件
  upload: (
    file: File,
    onProgress?: (progress: number) => void,
    folder = '',
  ): Promise<ApiResponse<{ path: string }>> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('folder', folder)
    return request.post('/storage/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const progress = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total,
          )
          onProgress(progress)
        }
      },
    })
  },

  // 获取文件列表
  getFileList: (folder?: string): Promise<ApiResponse<FileItem[]>> => {
    return request.get('/storage/list', { params: { folder } })
  },

  // 删除文件
  deleteFile: (path: string): Promise<ApiResponse> => {
    return request.post('/storage/delete', { path })
  },

  download: (path: string): Promise<Blob> => {
    return request.get('/storage/download', {
      params: { path },
      responseType: 'blob',
    })
  },
}
