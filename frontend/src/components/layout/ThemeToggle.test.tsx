import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { THEME_STORAGE_KEY } from '@/lib/theme'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ThemeToggle } from './ThemeToggle'

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('ThemeToggle', () => {
  it('nút có nhãn và mở ra ba lựa chọn, mặc định "Theo hệ thống"', async () => {
    renderWithProviders(<ThemeToggle />)
    await userEvent.click(screen.getByRole('button', { name: 'Giao diện' }))

    const options = screen.getAllByRole('menuitemradio').map((option) => option.textContent)
    expect(options).toEqual(['Sáng', 'Tối', 'Theo hệ thống'])
    expect(screen.getByRole('menuitemradio', { name: 'Theo hệ thống' })).toBeChecked()
  })

  it('chọn "Tối" bật chế độ tối và lưu lựa chọn', async () => {
    renderWithProviders(<ThemeToggle />)
    await userEvent.click(screen.getByRole('button', { name: 'Giao diện' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Tối' }))

    expect(document.documentElement).toHaveClass('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('khôi phục lựa chọn đã lưu khi dựng lại', async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    renderWithProviders(<ThemeToggle />)
    expect(document.documentElement).toHaveClass('dark')
    await userEvent.click(screen.getByRole('button', { name: 'Giao diện' }))
    expect(screen.getByRole('menuitemradio', { name: 'Tối' })).toBeChecked()
  })
})
