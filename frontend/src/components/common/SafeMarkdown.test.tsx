import { render, screen } from '@testing-library/react'
import { safeUrl } from '@/lib/safeUrl'
import { SafeMarkdown } from './SafeMarkdown'

describe('safeUrl', () => {
  it.each([
    ['https://gearvn.example/p/1', 'https://gearvn.example/p/1'],
    ['http://mock-shop.example/p/1?a=1&b=2', 'http://mock-shop.example/p/1?a=1&b=2'],
    ['HTTPS://MOCK.EXAMPLE', 'HTTPS://MOCK.EXAMPLE'],
    ['  https://a.example  ', 'https://a.example'],
    ['mailto:ban@example.com', 'mailto:ban@example.com'],
  ])('giữ %s', (input, expected) => {
    expect(safeUrl(input)).toBe(expected)
  })

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    ' javascript:alert(1)',
    'java\nscript:alert(1)',
    'java\tscript:alert(1)',
    'jav&#x61;script:alert(1)',
    'data:text/html;base64,PHNjcmlwdD4=',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    'ftp://x.example',
    '//evil.example/x',
    '/relative/path',
    'products/12',
    '#anchor',
    '',
  ])('bỏ %j', (input) => {
    expect(safeUrl(input)).toBe('')
  })
})

describe('SafeMarkdown', () => {
  it('liên kết http(s) mở tab mới và có rel an toàn', () => {
    render(<SafeMarkdown>{'[Mở trang](https://gearvn.example/p/1)'}</SafeMarkdown>)
    const link = screen.getByRole('link', { name: 'Mở trang' })
    expect(link).toHaveAttribute('href', 'https://gearvn.example/p/1')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it.each([
    '[bấm vào](javascript:alert(1))',
    '[bấm vào](JaVaScRiPt:alert(1))',
    '[bấm vào](java\nscript:alert(1))',
    '[bấm vào](data:text/html;base64,PHNjcmlwdD4=)',
    '[bấm vào](vbscript:msgbox(1))',
    '[bấm vào](/admin)',
  ])('%j không tạo liên kết bấm được, chữ vẫn hiện', (markdown) => {
    const { container } = render(<SafeMarkdown>{markdown}</SafeMarkdown>)
    expect(screen.queryByRole('link')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(screen.getByText(/bấm vào/)).toBeInTheDocument()
  })

  it('liên kết tự động (autolink) cũng bị lọc scheme', () => {
    const { container } = render(<SafeMarkdown>{'<javascript:alert(1)>'}</SafeMarkdown>)
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
  })

  it('HTML thô hiện như văn bản, không dựng phần tử', () => {
    const { container } = render(
      <SafeMarkdown>
        {'Giá tốt <img src=x onerror=alert(1)> <script>alert(1)</script> <b>đậm</b>'}
      </SafeMarkdown>,
    )
    expect(container.querySelector('img, script, b')).toBeNull()
    expect(container.textContent).toContain('Giá tốt')
  })

  it('ảnh Markdown bị bỏ (không tải tài nguyên ngoài), chữ thay thế còn lại', () => {
    const { container } = render(
      <SafeMarkdown>{'![Ảnh máy](https://x.example/a.png)'}</SafeMarkdown>,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('Ảnh máy')
  })

  it('hiển thị định dạng cơ bản: đậm, danh sách, tiêu đề', () => {
    render(
      <SafeMarkdown>{'## Kết quả\n\n- **Máy A** rẻ nhất\n- Máy B\n\n1. Một\n2. Hai'}</SafeMarkdown>,
    )
    expect(screen.getByText('Kết quả')).toBeInTheDocument()
    expect(screen.getByText('Máy A').tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
  })

  it('chuỗi rỗng không lỗi', () => {
    const { container } = render(<SafeMarkdown>{''}</SafeMarkdown>)
    expect(container.querySelector('a')).toBeNull()
  })
})
