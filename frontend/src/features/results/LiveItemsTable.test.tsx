import { render, screen, within } from '@testing-library/react'
import { LiveItemsTable } from './LiveItemsTable'

const item = {
  site: 'gearvn',
  title: 'Loa Mock Bluetooth X1',
  price: 1_290_000,
  url: 'https://mock-gearvn.example/p/loa-x1',
  scraped_at: '2026-10-16T02:00:00Z',
}

describe('LiveItemsTable', () => {
  it('không có kết quả: không dựng gì', () => {
    const { container } = render(<LiveItemsTable items={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('hiện nhãn "chưa chuẩn hóa thông số" và bảng Tên, Giá, Trang, Liên kết', () => {
    render(<LiveItemsTable items={[item]} />)
    const labels = screen.getAllByText('Tìm trực tiếp – chưa chuẩn hóa thông số')
    expect(labels.length).toBeGreaterThan(0)
    const table = screen.getByRole('table', { name: 'Tìm trực tiếp – chưa chuẩn hóa thông số' })
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Tên', 'Giá', 'Trang', 'Liên kết'])
    expect(within(table).getByText('Loa Mock Bluetooth X1')).toBeInTheDocument()
    expect(within(table).getByText('1.290.000 ₫')).toBeInTheDocument()
    const link = within(table).getByRole('link', { name: 'Mở trang: Loa Mock Bluetooth X1' })
    expect(link).toHaveAttribute('href', item.url)
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('không rõ giá thì hiện chữ thay vì số; URL nguy hiểm không thành liên kết', () => {
    render(
      <LiveItemsTable
        items={[{ ...item, price: null, url: 'javascript:alert(1)', title: 'Loa Mock lạ' }]}
      />,
    )
    expect(screen.getByText('Không rõ giá')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('tiêu đề chứa HTML được hiện như văn bản', () => {
    const { container } = render(
      <LiveItemsTable items={[{ ...item, title: '<img src=x onerror=alert(1)> Loa' }]} />,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/Loa/)).toBeInTheDocument()
  })
})
