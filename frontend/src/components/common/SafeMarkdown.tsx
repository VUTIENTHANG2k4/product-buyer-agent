import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import { safeUrl } from '@/lib/safeUrl'

const inline = 'font-semibold'

/**
 * Hiển thị Markdown của câu trả lời. HTML thô không được diễn giải (hiện như văn bản), ảnh bị bỏ
 * (chỉ giữ chữ thay thế), liên kết mở tab mới với `rel="noopener noreferrer"`.
 */
export function SafeMarkdown({ children }: { children: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed break-words">
      <Markdown
        urlTransform={safeUrl}
        components={{
          a({ href, children: content }: { href?: string; children?: ReactNode }) {
            if (!href) return <span>{content}</span>
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline underline-offset-2"
              >
                {content}
              </a>
            )
          },
          // Ảnh không được tải: chỉ hiện chữ thay thế.
          img: ({ alt }) => <span>{alt}</span>,
          h1: ({ children: content }) => <p className={`${inline} text-base`}>{content}</p>,
          h2: ({ children: content }) => <p className={`${inline} text-base`}>{content}</p>,
          h3: ({ children: content }) => <p className={inline}>{content}</p>,
          ul: ({ children: content }) => <ul className="list-disc space-y-1 pl-5">{content}</ul>,
          ol: ({ children: content }) => <ol className="list-decimal space-y-1 pl-5">{content}</ol>,
          code: ({ children: content }) => (
            <code className="rounded-sm bg-muted px-1 py-0.5 text-xs">{content}</code>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  )
}
