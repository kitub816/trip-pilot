import axios from 'axios'
import type {
  TripFormData,
  TripPlan,
  TripPlanResponse,
  ExtractionPreview,
  StoredTripPlanResponse
} from '@/types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || window.location.origin

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' }
})

export class PlanningRequestError extends Error {
  constructor(message: string, public readonly recoverable: boolean) {
    super(message)
    this.name = 'PlanningRequestError'
  }
}

export async function generateTripPlan(
  formData: TripFormData,
  signal?: AbortSignal,
  recoveryId?: string
): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData, {
      signal,
      timeout: 600000,
      headers: recoveryId ? { 'X-Trip-Plan-ID': recoveryId } : undefined
    })
    return response.data
  } catch (error) {
    if (axios.isCancel(error)) throw new PlanningRequestError('规划已取消，可稍后检查恢复状态', true)
    if (axios.isAxiosError(error)) {
      if (error.code === 'ECONNABORTED') {
        throw new PlanningRequestError('等待规划结果超时，可稍后检查恢复状态', true)
      }
      const message = error.response?.data?.detail || error.response?.data?.message || '生成旅行计划失败'
      const status = error.response?.status
      throw new PlanningRequestError(message, status == null || status >= 500)
    }
    throw new PlanningRequestError('生成旅行计划失败', true)
  }
}

export async function getStoredTripPlan(planId: string): Promise<StoredTripPlanResponse> {
  try {
    const response = await apiClient.get<StoredTripPlanResponse>(
      `/api/trip/plans/${encodeURIComponent(planId)}`
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      throw new Error(error.response?.data?.message || '无法读取待恢复的旅行计划')
    }
    throw error
  }
}

export async function getTripPlan(planId: string): Promise<{ data: TripPlan; version: number }> {
  const response = await getStoredTripPlan(planId)
  if (!response.data) throw new Error('计划数据不可用')
  return { data: response.data, version: response.version }
}

export async function resumeTripPlan(planId: string): Promise<StoredTripPlanResponse> {
  try {
    const response = await apiClient.post<StoredTripPlanResponse>(
      `/api/trip/plans/${encodeURIComponent(planId)}/resume`,
      undefined,
      { timeout: 600000 }
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (error.code === 'ECONNABORTED') throw new Error('恢复请求仍在处理，请稍后检查状态')
      throw new Error(error.response?.data?.message || '恢复旅行计划失败')
    }
    throw error
  }
}

export async function updateTripPlan(planId: string, expectedVersion: number, data: TripPlan): Promise<{ data: TripPlan; version: number }> {
  try {
    const response = await apiClient.put(`/api/trip/plans/${encodeURIComponent(planId)}`, {
      expected_version: expectedVersion,
      data
    })
    if (!response.data.data) throw new Error('更新后的计划不可用')
    return { data: response.data.data, version: response.data.version }
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.message
      throw new Error(typeof message === 'string' ? message : '保存失败，请刷新后重试')
    }
    throw error
  }
}

export async function getAttractionPhoto(name: string, signal?: AbortSignal): Promise<string | null> {
  const response = await apiClient.get('/api/poi/photo', { params: { name }, signal })
  return response.data?.success ? response.data?.data?.photo_url || null : null
}

export default apiClient

export async function extractConstraints(text: string): Promise<ExtractionPreview> {
  try {
    const response = await apiClient.post<ExtractionPreview>('/api/trip/extract', { text })
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.message
      throw new Error(typeof message === 'string' ? message : '提取失败，请手动填写约束')
    }
    throw error
  }
}
