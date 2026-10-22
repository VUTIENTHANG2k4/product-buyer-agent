import { ApiError } from '@/api/client'
import { startRunErrorMessage } from './startRunError'

const conflict = (code: string, details?: unknown) => new ApiError(409, code, 'từ máy chủ', details)

describe('startRunErrorMessage', () => {
  it('OFFLINE_MODE có câu riêng', () => {
    expect(startRunErrorMessage(conflict('OFFLINE_MODE'))).toMatch(/chế độ offline/)
  })

  it('SCRAPE_ALREADY_RUNNING nêu mã lượt khi details.run_id là số; sai kiểu hoặc thiếu thì câu chung', () => {
    expect(startRunErrorMessage(conflict('SCRAPE_ALREADY_RUNNING', { run_id: 12 }))).toContain(
      '#12',
    )
    for (const details of [undefined, null, 'x', { run_id: '12' }, {}]) {
      expect(startRunErrorMessage(conflict('SCRAPE_ALREADY_RUNNING', details))).toBe(
        'Nhóm này đang có một lượt chạy khác.',
      )
    }
  })

  it('SITE_COOLDOWN nêu giờ Việt Nam; retry_after hỏng hoặc thiếu thì không nêu giờ', () => {
    expect(
      startRunErrorMessage(conflict('SITE_COOLDOWN', { retry_after: '2026-10-17T03:30:00Z' })),
    ).toBe('Trang này đang nghỉ sau khi bị chặn, thử lại được sau 10:30 17/10/2026.')
    for (const details of [undefined, {}, { retry_after: 5 }, { retry_after: 'không phải ngày' }]) {
      expect(startRunErrorMessage(conflict('SITE_COOLDOWN', details))).toBe(
        'Trang này đang nghỉ sau khi bị chặn.',
      )
    }
  })

  it('mã khác dùng thông điệp của máy chủ; lỗi lạ dùng câu chung tiếng Việt', () => {
    expect(startRunErrorMessage(new ApiError(422, 'VALIDATION_ERROR', 'Nhóm sai'))).toBe('Nhóm sai')
    expect(startRunErrorMessage(new Error('boom'))).toBe('Đã có lỗi xảy ra. Hãy thử lại.')
  })
})
