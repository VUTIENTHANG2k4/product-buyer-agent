import { safeUrl } from './safeUrl'

describe('safeUrl · dạng che mắt (QA M8)', () => {
  it.each([
    ['khoảng trắng Unicode đầu', String.fromCharCode(0xa0) + 'javascript:alert(1)'],
    ['BOM đầu', String.fromCharCode(0xfeff) + 'javascript:alert(1)'],
    ['zero-width space đầu', String.fromCharCode(0x200b) + 'javascript:alert(1)'],
    ['ký tự điều khiển C0 đầu', String.fromCharCode(1) + 'javascript:alert(1)'],
    ['NUL đầu', String.fromCharCode(0) + 'javascript:alert(1)'],
    ['xuống dòng giữa tên scheme (CR)', 'java\rscript:alert(1)'],
    ['NUL giữa tên scheme', 'java' + String.fromCharCode(0) + 'script:alert(1)'],
    ['dấu hai chấm toàn chiều rộng', 'javascript' + String.fromCharCode(0xff1a) + 'alert(1)'],
    ['chữ J toàn chiều rộng', String.fromCharCode(0xff2a) + 'avascript:alert(1)'],
    ['thực thể thập phân', '&#106;avascript:alert(1)'],
    ['thực thể hex', '&#x6A;avascript:alert(1)'],
    ['thực thể có tên cho dấu hai chấm', 'javascript&colon;alert(1)'],
    ['percent-encoding', '%6Aavascript:alert(1)'],
    ['data:image', 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='],
    ['blob:', 'blob:https://x.example/uuid'],
    ['about:', 'about:blank'],
    ['scheme lạ giống https', 'httpss://x.example'],
    ['scheme http có khoảng trắng', 'http ://x.example'],
    ['protocol-relative sau khoảng trắng', '  //evil.example'],
    ['backslash kiểu //', '\\\\evil.example'],
  ])('bỏ %s', (_name, input) => {
    expect(safeUrl(input)).toBe('')
  })

  it.each([
    ['https://gearvn.example/p?x=1#a', 'https://gearvn.example/p?x=1#a'],
    [
      String.fromCharCode(0xa0) + 'https://x.example' + String.fromCharCode(0xa0),
      'https://x.example',
    ],
    ['\thttp://x.example\n', 'http://x.example'],
    ['https://tiếng-việt.example/đường-dẫn', 'https://tiếng-việt.example/đường-dẫn'],
  ])('giữ %j', (input, expected) => {
    expect(safeUrl(input)).toBe(expected)
  })

  it('URL rất dài (1 MB) trả về nguyên vẹn', () => {
    const url = `https://x.example/${'a'.repeat(1_000_000)}`
    expect(safeUrl(url)).toBe(url)
  })

  it('1 MB khoảng trắng rồi javascript: bị bỏ, không treo', () => {
    expect(safeUrl(`${' '.repeat(1_000_000)}javascript:alert(1)`)).toBe('')
  })
})
