import { expect, test, type Page } from '@playwright/test'

type LiveCase = {
  id: string
  city: string
  startDate: string
  endDate: string
  travelDays: number
  transportation: '公共交通' | '步行' | '自驾'
  accommodation: '经济型酒店' | '舒适型酒店'
  preferences: string[]
  budget: number
  walkingLimit?: number
  segmentLimit: number
  verifyPdf?: boolean
}

const liveEnabled = process.env.TRIPPILOT_LIVE_E2E === '1'
const selectedCases = new Set(
  (process.env.TRIPPILOT_LIVE_CASES || 'xi-an').split(',').map(value => value.trim()),
)

const cases: LiveCase[] = [
  {
    id: 'xi-an', city: '西安', startDate: '2026-09-28', endDate: '2026-09-30',
    travelDays: 3, transportation: '公共交通', accommodation: '经济型酒店',
    preferences: ['历史文化', '购物'], budget: 3000, walkingLimit: 6, segmentLimit: 60,
  },
  {
    id: 'shanghai', city: '上海', startDate: '2026-09-29', endDate: '2026-09-30',
    travelDays: 2, transportation: '步行', accommodation: '舒适型酒店',
    preferences: ['艺术', '美食'], budget: 5000, walkingLimit: 20, segmentLimit: 120,
    verifyPdf: true,
  },
  {
    id: 'hangzhou', city: '杭州', startDate: '2026-09-29', endDate: '2026-09-30',
    travelDays: 2, transportation: '自驾', accommodation: '经济型酒店',
    preferences: ['自然风光', '休闲'], budget: 5000, segmentLimit: 120,
  },
]

async function chooseSelect(page: Page, label: string, option: string) {
  const field = page.locator('.ant-form-item').filter({ hasText: label })
  await field.locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option')
    .filter({ hasText: option }).click()
  await expect(field.locator('.ant-select-selection-item')).toContainText(option)
}

for (const liveCase of cases) {
  test(liveCase.id + ' reaches a complete result page', async ({ page }) => {
    test.skip(!liveEnabled || !selectedCases.has(liveCase.id),
      'requires the local backend and real configured providers')
    test.setTimeout(11 * 60 * 1000)
    await page.addInitScript(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    let submitted: Record<string, unknown> | undefined
    page.on('request', request => {
      if (request.url().includes('/api/trip/plan/stream')) {
        submitted = request.postDataJSON() as Record<string, unknown>
      }
    })

    await page.goto('/')
    await page.getByPlaceholder('例如: 北京').fill(liveCase.city)

    const dates = page.getByPlaceholder('选择日期')
    await dates.nth(0).click()
    await page.locator('.ant-picker-dropdown:visible [title="' + liveCase.startDate + '"]').click()
    await dates.nth(1).click()
    await page.locator('.ant-picker-dropdown:visible [title="' + liveCase.endDate + '"]').click()

    await chooseSelect(page, '交通方式', liveCase.transportation)
    await chooseSelect(page, '住宿偏好', liveCase.accommodation)
    for (const preference of liveCase.preferences) {
      await page.getByRole('checkbox', { name: new RegExp(preference) }).check()
    }
    await page.getByRole('spinbutton', { name: '总预算上限（元）' })
      .fill(String(liveCase.budget))
    if (liveCase.walkingLimit != null) {
      await page.locator('.ant-form-item').filter({ hasText: '每日步行上限（公里）' })
        .getByRole('spinbutton').fill(String(liveCase.walkingLimit))
    }
    await page.locator('.ant-form-item').filter({ hasText: '单段交通上限（分钟）' })
      .getByRole('spinbutton').fill(String(liveCase.segmentLimit))
    await page.getByRole('checkbox', { name: /仅安排无需预约/ }).uncheck()

    await page.getByRole('button', { name: '开始规划我的旅行' }).click()
    const outcome = await Promise.race([
      page.waitForURL(/\/result$/, { timeout: 10 * 60 * 1000 })
        .then(() => ({ kind: 'result' as const, message: '' })),
      page.locator('.ant-message-error').last()
        .waitFor({ state: 'visible', timeout: 10 * 60 * 1000 })
        .then(async () => ({
          kind: 'error' as const,
          message: (await page.locator('.ant-message-error').last().textContent()) || '未知规划错误',
        })),
    ])
    if (outcome.kind === 'error') throw new Error('页面规划失败：' + outcome.message.trim())
    expect(submitted).toMatchObject({
      city: liveCase.city,
      start_date: liveCase.startDate,
      end_date: liveCase.endDate,
      travel_days: liveCase.travelDays,
      transportation: liveCase.transportation,
      accommodation: liveCase.accommodation,
      preferences: liveCase.preferences,
      budget_limit: liveCase.budget,
      max_single_transport_minutes: liveCase.segmentLimit,
      avoid_reservation_required: false,
    })
    if (liveCase.walkingLimit != null) {
      expect(submitted).toMatchObject({ max_daily_walking_km: liveCase.walkingLimit })
    }
    await expect(page.getByText(liveCase.city + '旅行计划', { exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: /第\d+天/ })).toHaveCount(liveCase.travelDays)
    await expect(page.getByText(/预算明细/).first()).toBeVisible()
    await expect(page.getByText(/天气信息/).first()).toBeVisible()
    const lastDay = page.getByRole('tab', { name: /第\d+天/ }).last()
    await lastDay.click()
    await expect(lastDay).toHaveAttribute('aria-expanded', 'true')

    if (liveCase.verifyPdf) {
      await page.getByRole('button', { name: /导出行程/ }).click()
      const downloadPromise = page.waitForEvent('download')
      await page.getByText('导出为PDF', { exact: false }).click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toMatch(/\.pdf$/)
      expect(await download.failure()).toBeNull()
      const stream = await download.createReadStream()
      const chunks: Buffer[] = []
      for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
      const bytes = Buffer.concat(chunks)
      expect(bytes.subarray(0, 5).toString()).toBe('%PDF-')
      expect(bytes.length).toBeGreaterThan(1000)
    }
  })
}
