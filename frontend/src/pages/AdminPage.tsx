import { useState } from 'react'
import { QueryBoundary } from '@/components/common/QueryBoundary'
import { EmptyState } from '@/components/common/states'
import { Skeleton } from '@/components/ui/skeleton'
import { useSources } from '@/features/admin/api'
import { ChallengeDialog, type ChallengeOutcome } from '@/features/admin/ChallengeDialog'
import { OfflineBanner } from '@/features/admin/OfflineBanner'
import { RunsSection } from '@/features/admin/RunsSection'
import { SourceCard } from '@/features/admin/SourceCard'
import { strings } from '@/lib/strings'

/** Quản trị thu thập: banner offline, thẻ nguồn (chạy ngay theo nhóm), bảng lượt chạy, xử lý challenge. */
export function AdminPage() {
  const text = strings.admin
  const sources = useSources()
  const [challengeRun, setChallengeRun] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  function resolved(outcome: ChallengeOutcome) {
    setChallengeRun(null)
    setNotice(outcome === 'answered' ? text.answeredNotice : text.notPendingNotice)
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">{strings.pages.admin.title}</h1>
      <OfflineBanner />
      {notice ? (
        <p role="status" className="rounded-lg border bg-muted/40 p-3 text-sm">
          {notice}
        </p>
      ) : null}
      <section aria-labelledby="sources-heading" className="space-y-4">
        <h2 id="sources-heading" className="text-xl font-semibold">
          {text.sourcesTitle}
        </h2>
        <QueryBoundary
          query={sources}
          errorTitle={text.sourcesLoadError}
          isEmpty={(data) => data.items.length === 0}
          empty={<EmptyState title={text.noSources} />}
          skeleton={
            <div className="grid gap-4 md:grid-cols-2">
              <Skeleton className="h-48 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          }
        >
          {(data) => (
            <ul className="grid gap-4 md:grid-cols-2">
              {data.items.map((source) => (
                <SourceCard
                  key={source.key}
                  source={source}
                  onHandle={(runId) => {
                    setNotice(null)
                    setChallengeRun(runId)
                  }}
                />
              ))}
            </ul>
          )}
        </QueryBoundary>
      </section>
      <RunsSection
        sources={sources.data?.items ?? []}
        onHandle={(runId) => {
          setNotice(null)
          setChallengeRun(runId)
        }}
      />
      <ChallengeDialog
        runId={challengeRun}
        onOpenChange={(open) => {
          if (!open) setChallengeRun(null)
        }}
        onResolved={resolved}
      />
    </div>
  )
}
