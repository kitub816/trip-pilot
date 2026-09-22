import axios from 'axios'
import type { TripFormData, TripPlan, TripPlanResponse, ExtractionPreview } from '@/types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || window.location.origin

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' }
})

export async function generateTripPlan(formData: TripFormData, signal?: AbortSignal): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData, { signal })
    return response.data
  } catch (error) {
    if (axios.isCancel(error)) throw new Error('规划已取消')
    if (axios.isAxiosError(error)) {
      throw new Error(error.response?.data?.detail || error.response?.data?.message || '生成旅行计划失败')
    }
    throw new Error('生成旅行计划失败')
  }
}

export async function getTripPlan(planId: string): Promise<{ data: TripPlan; version: number }> {
  const response = await apiClient.get(`/api/trip/plans/${encodeURIComponent(planId)}`)
  if (!response.data.data) throw new Error('计划数据不可用')
  return { data: response.data.data, version: response.data.version }
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
      throw new Error(typeof message === "string" ? message : "保存失败，请刷新后重试")
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
    const response = await apiClient.post<ExtractionPreview>("/api/trip/extract", { text })
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.message
      throw new Error(typeof message === "string" ? message : "提取失败，请手动填写约束")
    }
    throw error
  }
}
