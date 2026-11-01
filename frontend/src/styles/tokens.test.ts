/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Đọc thẳng tệp nguồn: Vitest không nạp nội dung CSS qua `?raw`.
const css = readFileSync(resolve(import.meta.dirname, 'globals.css'), 'utf-8')
  .split(String.fromCharCode(13))
  .join('')
const indexHtml = readFileSync(resolve(import.meta.dirname, '../../index.html'), 'utf-8')

/** Lấy các khai báo `--tên: #hex;` trong khối có bộ chọn `selector` (không lồng nhau). */
function tokensOf(selector: string): Record<string, string> {
  const start = css.indexOf(`\n${selector} {`)
  expect(start, `không thấy khối ${selector}`).toBeGreaterThanOrEqual(0)
  const end = css.indexOf('\n}', start)
  const tokens: Record<string, string> = {}
  for (const match of css.slice(start, end).matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    tokens[match[1] as string] = (match[2] as string).trim()
  }
  return tokens
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const value = parseInt(hex.slice(i, i + 2), 16) / 255
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return (
    0.2126 * (channels[0] as number) +
    0.7152 * (channels[1] as number) +
    0.0722 * (channels[2] as number)
  )
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (light + 0.05) / (dark + 0.05)
}

const light = tokensOf(':root')
const dark = tokensOf('.dark')

describe('token màu (docs/08 §5)', () => {
  it('chế độ tối khai báo đủ mọi token màu của chế độ sáng (không rơi về màu sáng trên nền tối)', () => {
    const colorTokens = Object.keys(light).filter((name) => /^#/.test(light[name] as string))
    const missing = colorTokens.filter((name) => !(name in dark))
    expect(missing).toEqual([])
  })

  it('mọi token màu đều là mã hex 6 ký tự hợp lệ ở cả hai chế độ', () => {
    for (const tokens of [light, dark]) {
      for (const [name, value] of Object.entries(tokens)) {
        if (value.startsWith('#')) expect(value, name).toMatch(/^#[0-9a-f]{6}$/i)
      }
    }
  })

  it('mọi token màu đều có ánh xạ --color-* trong @theme để Tailwind dùng được', () => {
    const colorTokens = Object.keys(light).filter((name) => /^#/.test(light[name] as string))
    const unmapped = colorTokens.filter((name) => !css.includes(`--color-${name}: var(--${name});`))
    expect(unmapped).toEqual([])
  })

  it('có token --primary-hover ở cả hai chế độ và khác --primary (để trạng thái hover nhìn thấy được)', () => {
    expect(light['primary-hover']).toBeDefined()
    expect(dark['primary-hover']).toBeDefined()
    expect(light['primary-hover']).not.toBe(light['primary'])
    expect(dark['primary-hover']).not.toBe(dark['primary'])
  })

  describe.each([
    ['sáng', light],
    ['tối', dark],
  ])('độ tương phản chữ (WCAG AA ≥ 4.5) · chế độ %s', (_mode, t) => {
    it.each([
      ['foreground', 'background'],
      ['card-foreground', 'card'],
      ['primary-foreground', 'primary'],
      ['primary-foreground', 'primary-hover'],
      ['primary', 'card'],
      ['primary', 'accent'],
      ['primary', 'background'],
      ['muted-foreground', 'background'],
      ['muted-foreground', 'muted'],
      ['muted-foreground', 'card'],
      ['foreground', 'muted'],
      ['accent-foreground', 'accent'],
      ['secondary-foreground', 'secondary'],
      ['destructive', 'background'],
      ['destructive', 'card'],
      ['success', 'background'],
      ['warning', 'background'],
      ['accent-deal', 'background'],
    ])('%s trên %s', (fg, bg) => {
      expect(contrast(t[fg] as string, t[bg] as string)).toBeGreaterThanOrEqual(4.5)
    })

    it('vòng focus (--ring) nổi trên nền với tỷ lệ ≥ 3 (WCAG 1.4.11)', () => {
      expect(contrast(t['ring'] as string, t['background'] as string)).toBeGreaterThanOrEqual(3)
    })
  })
})

describe('index.html', () => {
  it('khai báo ngôn ngữ tiếng Việt cho trình đọc màn hình và phông chữ', () => {
    expect(indexHtml).toMatch(/<html[^>]*\blang="vi"/)
  })

  it('có viewport responsive để màn hình 360 px không bị thu nhỏ', () => {
    expect(indexHtml).toMatch(
      /<meta name="viewport" content="width=device-width, initial-scale=1\.0"/,
    )
  })

  it('bật chế độ tối theo hệ điều hành bằng lớp .dark và có try/catch khi matchMedia không có', () => {
    expect(indexHtml).toContain("matchMedia('(prefers-color-scheme: dark)')")
    expect(indexHtml).toContain("classList.add('dark')")
    expect(indexHtml).toMatch(/try\s*{[\s\S]*}\s*catch/)
  })
})
