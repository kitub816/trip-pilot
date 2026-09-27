import axios from 'axios'
import type {
  TripFormData,
  TripPlan,
  TripPlanResponse,
  ExtractionPreview,
  StoredTripPlanResponse
} from '@/types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || window.location.origin
export const PLAN_OWNER_KEY = 'tripPlanOwnerToken'

export function getOrCreatePlanOwnerToken(): string {
  const existing = localStorage.getItem(PLAN_OWNER_KEY)
  if (existing && /^[0-9a-f]{64}$/.test(existing)) return existing
  const created = Array.from(
    crypto.getRandomValues(new Uint8Array(32)),
    value => value.toString(16).padStart(2, '0')
  ).join('')
  localStorage.setItem(PLAN_OWNER_KEY, created)
  return created
}

function ownerHeaders(): Record<string, string> {
  return { 'X-Trip-Owner-Token': getOrCreatePlanOwnerToken() }
}

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
  recoveryId?: string,
  onProgress?: (stage: string) => void
): Promise<TripPlanResponse> {
  const controller = new AbortController()
  let timedOut = false
  const cancel = () => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) controller.abort()
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, 600000)
  try {
    const response = await fetch(`${API_BASE_URL}/api/trip/plan/stream`, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        ...ownerHeaders(),
        ...(recoveryId ? { 'X-Trip-Plan-ID': recoveryId } : {})
      },
      body: JSON.stringify(formData)
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new PlanningRequestError(body.detail || body.message || '生成旅行计划失败', response.status >= 500)
    }
    if (!response.body) throw new PlanningRequestError('浏览器不支持规划进度流', true)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result: TripPlanResponse | null = null
    const handleFrame = (frame: string) => {
      const event = frame.match(/^event: (.+)$/m)?.[1]
      const data = frame.split('\n').filter(line => line.startsWith('data: '))
        .map(line => line.slice(6)).join('\n')
      if (!event || !data) return
      const payload = JSON.parse(data)
      if (event === 'progress') onProgress?.(payload.stage)
      if (event === 'result') result = payload as TripPlanResponse
      if (event === 'error') {
        throw new PlanningRequestError(payload.message || '生成旅行计划失败',
          (payload.status_code || 500) >= 500)
      }
    }
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let boundary = buffer.search(/\r?\n\r?\n/)
      while (boundary !== -1) {
        handleFrame(buffer.slice(0, boundary).replace(/\r\n/g, '\n'))
        const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)![0]
        buffer = buffer.slice(boundary + separator.length)
        boundary = buffer.search(/\r?\n\r?\n/)
      }
      if (result) return result
      if (done) break
    }
    throw new PlanningRequestError('规划连接中断，可稍后检查恢复状态', true)
  } catch (error) {
    if (error instanceof PlanningRequestError) throw error
    if (controller.signal.aborted) throw new PlanningRequestError(
      timedOut ? '等待规划结果超时，可稍后检查恢复状态' : '规划已取消，可稍后检查恢复状态', true)
    throw new PlanningRequestError('规划连接中断，可稍后检查恢复状态', true)
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}

export async function getStoredTripPlan(planId: string): Promise<StoredTripPlanResponse> {
  try {
    const response = await apiClient.get<StoredTripPlanResponse>(
      `/api/trip/plans/${encodeURIComponent(planId)}`,
      { headers: ownerHeaders() }
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
      { timeout: 600000, headers: ownerHeaders() }
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
    }, { headers: ownerHeaders() })
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
