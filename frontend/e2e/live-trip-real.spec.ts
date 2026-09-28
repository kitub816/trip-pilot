import { expect, test } from '@playwright/test'

const liveEnabled = process.env.TRIPPILOT_LIVE_E2E === '1'

test.skip(!liveEnabled, 'requires the local backend and real configured providers')

test('Xi an three-day request reaches a complete result page', async ({ page }) => {
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
  await page.getByPlaceholder('例如: 北京').fill('西安')

  const dates = page.getByPlaceholder('选择日期')
  await dates.nth(0).click()
  await page.locator('.ant-picker-dropdown:visible [title="2026-09-28"]').click()
  await dates.nth(1).click()
  await page.locator('.ant-picker-dropdown:visible [title="2026-09-30"]').click()

  await page.getByRole('checkbox', { name: /历史文化/ }).check()
  await page.getByRole('checkbox', { name: /购物/ }).check()
  await page.getByRole('spinbutton', { name: '总预算上限（元）' }).fill('3000')
  await page.locator('.ant-form-item').filter({ hasText: '每日步行上限（公里）' })
    .getByRole('spinbutton').fill('6')
  await page.locator('.ant-form-item').filter({ hasText: '单段交通上限（分钟）' })
    .getByRole('spinbutton').fill('60')
  await page.getByRole('checkbox', { name: /仅安排无需预约/ }).uncheck()

  await page.getByRole('button', { name: '开始规划我的旅行' }).click()
  await expect(page).toHaveURL(/\/result$/, { timeout: 10 * 60 * 1000 })
  expect(submitted).toMatchObject({
    city: '西安',
    start_date: '2026-09-28',
    end_date: '2026-09-30',
    travel_days: 3,
    transportation: '公共交通',
    accommodation: '经济型酒店',
    preferences: ['历史文化', '购物'],
    budget_limit: 3000,
    max_daily_walking_km: 6,
    max_single_transport_minutes: 60,
    avoid_reservation_required: false,
  })
  await expect(page.getByText('西安', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('tab', { name: /第[123]天/ })).toHaveCount(3)
  await expect(page.getByText('西安城墙', { exact: true })).toBeVisible()
})
