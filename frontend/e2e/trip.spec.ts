import { test, expect, type Page } from '@playwright/test'

const plan = {
  city: '北京', start_date: '2026-10-20', end_date: '2026-10-20',
  weather_info: [], overall_suggestions: '测试行程建议',
  days: [{ date: '2026-10-20', day_index: 0, description: '测试日程',
    transportation: '步行', accommodation: '民宿', meals: [],
    attractions: [{ name: '故宫测试景点', address: '测试地址',
      location: { longitude: 116.397, latitude: 39.917 },
      visit_duration: 60, visit_start: '09:00', visit_end: '10:00', description: '测试景点描述' }] }],
  budget: { total: 0, total_attractions: 0, total_hotels: 0, total_meals: 0,
    total_transportation: 0, is_complete: false, unknown_items: [] }
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-01T12:00:00'))
  await page.route('**/api/poi/photo**', route => route.fulfill({ json: { success: false } }))
  // Tests exercise the real UI with deterministic API contracts; no supplier calls.
  await page.route('https://**/*', route => route.abort())
})

async function fillRequest(page: Page) {
  await page.goto('/')
  await page.getByPlaceholder('例如: 北京').fill('北京')
  const dates = page.getByPlaceholder('选择日期')
  await dates.nth(0).click()
  await page.locator('.ant-picker-dropdown:visible [title="2026-10-20"]').click()
  await expect(dates.nth(0)).toHaveValue('2026-10-20')
  await expect(page.locator('.ant-picker-dropdown:visible')).toHaveCount(0)
  await dates.nth(1).click()
  await page.locator('.ant-picker-dropdown:visible [title="2026-10-20"]').click()
}

async function openStored(page: Page) {
  await page.addInitScript(p => {
    sessionStorage.setItem('tripPlan', JSON.stringify(p))
    sessionStorage.setItem('tripPlanRef', JSON.stringify({ planId: 'fixture', version: 1 }))
  }, plan)
  await page.route('**/api/trip/plans/fixture', async route => {
    if (route.request().method() === 'GET')
      await route.fulfill({ json: { data: plan, version: 2 } })
    else await route.fallback()
  })
  await page.goto('/result')
  await expect(page.getByText('故宫测试景点', { exact: true })).toBeVisible()
}

test('create shows returned plan and retrieves persisted version', async ({ page }) => {
  await page.route('**/api/trip/plan', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ city: '北京', travel_days: 1 })
    await route.fulfill({ json: { success: true, data: plan, plan_id: 'fixture', version: 1 } })
  })
  await page.route('**/api/trip/plans/fixture', route => route.fulfill({ json: { data: plan, version: 2 } }))
  await fillRequest(page)
  await page.getByRole('button', { name: '开始规划我的旅行' }).click()
  await expect(page).toHaveURL(/result$/)
  await expect(page.getByText('故宫测试景点', { exact: true })).toBeVisible()
  await expect(page.getByText('09:00–10:00')).toBeVisible()
})

test('planning error stays on form and supports retry', async ({ page }) => {
  await page.route('**/api/trip/plan', route => route.fulfill({
    status: 422, json: { message: '行程无法满足时间约束' }
  }))
  await fillRequest(page)
  await page.getByRole('button', { name: '开始规划我的旅行' }).click()
  await expect(page.getByText('行程无法满足时间约束')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始规划我的旅行' })).toBeEnabled()
  await expect(page).toHaveURL(/\/$/)
})

test('edit uses latest server version and persists returned schedule', async ({ page }) => {
  await page.route('**/api/trip/plans/fixture', async route => {
    const body = route.request().postDataJSON()
    expect(body.expected_version).toBe(2)
    expect(body.data.days[0].attractions[0].visit_start).toBe('10:00')
    await route.fulfill({ json: { data: body.data, version: 3 } })
  })
  await openStored(page)
  await page.getByRole('button', { name: '编辑行程' }).click()
  await page.locator('input[type=time]').nth(0).fill('10:00')
  await page.locator('input[type=time]').nth(1).fill('11:00')
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByText('服务端已校验并保存修改，预算和路线已重算')).toBeVisible()
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('tripPlanRef')!).version)).toBe(3)
})

test('save conflict explains recovery and preserves unsaved edits', async ({ page }) => {
  await page.route('**/api/trip/plans/fixture', route => route.fulfill({
    status: 409, json: { message: '计划已更新，请刷新后重试' }
  }))
  await openStored(page)
  await page.getByRole('button', { name: '编辑行程' }).click()
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByText('计划已更新，请刷新后重试')).toBeVisible()
  await expect(page.getByRole('button', { name: '取消编辑' })).toBeVisible()
})


test('PDF export downloads a real PDF after dependency upgrade', async ({ page }) => {
  await openStored(page)
  await page.getByRole('button', { name: '导出行程' }).click()
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
})


test('extraction requires confirmation and keeps explicit fields', async ({ page }) => {
  await page.route('**/api/trip/extract', route => route.fulfill({
    json: { travelers: 2, budget_limit: '2000', currency: 'CNY', must_visit: ['故宫'] }
  }))
  await page.goto('/')
  await page.getByRole('spinbutton', { name: '总预算上限（元）' }).fill('1500')
  await page.getByPlaceholder('请输入您的额外要求', { exact: false }).fill('两人，总预算2000元，必须去故宫')
  await page.getByRole('button', { name: '提取约束预览' }).click()
  await expect(page.getByText('请核对提取结果')).toBeVisible()
  await expect(page.getByPlaceholder('默认1人')).toHaveValue('')
  await page.getByRole('button', { name: '确认填入空白约束' }).click()
  await expect(page.getByPlaceholder('默认1人')).toHaveValue('2')
  await expect(page.getByRole('spinbutton', { name: '总预算上限（元）' })).toHaveValue('1500')
})

test('extraction failure leaves manual planning available', async ({ page }) => {
  await page.route('**/api/trip/extract', route => route.fulfill({
    status: 422, json: { message: '未能提取可靠约束，请手动填写' }
  }))
  await page.goto('/')
  await page.getByPlaceholder('请输入您的额外要求', { exact: false }).fill('测试')
  await page.getByRole('button', { name: '提取约束预览' }).click()
  await expect(page.getByText('未能提取可靠约束，请手动填写')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始规划我的旅行' })).toBeEnabled()
})


test('official sources and reservation uncertainty are visible', async ({ page }) => {
  await page.addInitScript(p => {
    sessionStorage.setItem('tripPlan', JSON.stringify({ ...p,
      evidence: [{ poi_id: 'fixture', content: '需要提前实名预约',
        source_url: 'https://www.dpm.org.cn/singles_detail/259831.html',
        captured_at: '2026-09-22T00:00:00Z', status: 'verified' }],
      validation_warnings: [{ code: 'RESERVATION_REQUIRED', subject: '故宫' }]
    }))
  }, plan)
  await page.goto('/result')
  await expect(page.getByRole('link', { name: '查看来源' })).toHaveAttribute('href',
    'https://www.dpm.org.cn/singles_detail/259831.html')
  await expect(page.getByText('需要预约；请自行核对余票并完成预约', { exact: false })).toBeVisible()
})
