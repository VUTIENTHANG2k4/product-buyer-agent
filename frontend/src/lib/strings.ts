const appName = 'Buyer Agent'

// Chữ hiển thị cho người dùng, gom một chỗ để dễ sửa.
export const strings = {
  appName,
  skipToContent: 'Bỏ qua tới nội dung',
  documentTitle: (title: string | undefined) => (title ? `${title} · ${appName}` : appName),
  nav: {
    label: 'Điều hướng chính',
    home: 'Hỏi agent',
    lists: 'Danh sách mua',
    alerts: 'Cảnh báo',
    admin: 'Quản trị',
  },
  pages: {
    home: { title: 'Bạn muốn mua gì hôm nay?', description: 'Trang hội thoại sẽ làm ở T8.2.' },
    conversation: { title: 'Hội thoại', description: 'Mở lại hội thoại cũ sẽ làm ở T8.2.' },
    product: { title: 'Chi tiết sản phẩm', description: 'Sẽ làm ở T8.4.' },
    lists: { title: 'Danh sách mua', description: 'Sẽ làm ở T8.5.' },
    list: { title: 'Danh sách mua', description: 'Sẽ làm ở T8.5.' },
    alerts: { title: 'Cảnh báo giá', description: 'Sẽ làm ở T8.6.' },
    admin: { title: 'Quản trị', description: 'Sẽ làm ở T8.7.' },
    notFound: { title: 'Không tìm thấy trang', description: 'Đường dẫn này không tồn tại.' },
  },
  notFoundBack: 'Về trang chính',
  errors: {
    network: 'Không kết nối được máy chủ. Hãy kiểm tra lại và thử lại.',
    unknown: 'Đã có lỗi xảy ra. Hãy thử lại.',
    pageTitle: 'Trang gặp lỗi',
  },
  /** Hậu tố nhận diện mã (id) trên trang giữ chỗ. */
  idSuffix: (id: string | undefined) => (id ? ` (mã: ${id})` : ''),
} as const
