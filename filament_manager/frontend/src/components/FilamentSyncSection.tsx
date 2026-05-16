import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { RefreshCw, CloudDownload, CloudUpload, CheckCircle, AlertCircle } from 'lucide-react'
import { api } from '../api'
import type { FilamentSyncResult } from '../types'

export default function FilamentSyncSection({ isCloudConnected }: { isCloudConnected: boolean }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [lastResult, setLastResult] = useState<FilamentSyncResult & { op: 'pull' | 'push' } | null>(null)

  const { data: syncStatus, isLoading } = useQuery({
    queryKey: ['filament-sync-status'],
    queryFn: api.getFilamentSyncStatus,
    refetchInterval: 30_000,
  })

  const settingsMut = useMutation({
    mutationFn: api.patchFilamentSyncSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['filament-sync-status'] }),
  })

  const pullMut = useMutation({
    mutationFn: api.filamentSyncPull,
    onSuccess: (data) => {
      setLastResult({ ...data, op: 'pull' })
      qc.invalidateQueries({ queryKey: ['filament-sync-status'] })
      qc.invalidateQueries({ queryKey: ['spools'] })
    },
  })

  const pushMut = useMutation({
    mutationFn: api.filamentSyncPush,
    onSuccess: (data) => {
      setLastResult({ ...data, op: 'push' })
      qc.invalidateQueries({ queryKey: ['filament-sync-status'] })
      qc.invalidateQueries({ queryKey: ['spools'] })
    },
  })

  if (isLoading || !syncStatus) return null

  const busy = settingsMut.isPending || pullMut.isPending || pushMut.isPending

  const handleDirection = (dir: string) => {
    settingsMut.mutate({ enabled: syncStatus.enabled, direction: dir })
  }

  if (!isCloudConnected) {
    return <p className="text-xs text-yellow-500">{t('settings.filamentSync.requiresCloud')}</p>
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">{t('settings.filamentSync.hint')}</p>

      {/* Direction selector */}
      <div>
        <label className="label mb-1">{t('settings.filamentSync.direction')}</label>
        <div className="flex gap-2">
          {(['pull', 'push', 'bidirectional'] as const).map(dir => (
            <button
              key={dir}
              onClick={() => handleDirection(dir)}
              disabled={busy}
              className={`px-3 py-1.5 rounded text-xs border transition-colors
                ${syncStatus.direction === dir
                  ? 'bg-blue-600 border-blue-500 text-white'
                  : 'bg-surface-2 border-gray-600 text-gray-400 hover:border-gray-400 hover:text-gray-200'}`}
            >
              {t(`settings.filamentSync.dir_${dir}`)}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500 mt-1.5">
          {t(`settings.filamentSync.dirHint_${syncStatus.direction}`)}
        </p>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap gap-4 text-xs text-gray-400">
        <span>{t('settings.filamentSync.linked', { n: syncStatus.linked_spools, total: syncStatus.total_spools })}</span>
        {syncStatus.last_sync_at && (
          <span>{t('settings.filamentSync.lastSync', { date: new Date(syncStatus.last_sync_at).toLocaleString() })}</span>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap">
        {(syncStatus.direction === 'pull' || syncStatus.direction === 'bidirectional') && (
          <button
            onClick={() => { setLastResult(null); pullMut.mutate() }}
            disabled={busy}
            className="btn-secondary flex items-center gap-1.5 text-xs"
          >
            {pullMut.isPending
              ? <RefreshCw size={13} className="animate-spin" />
              : <CloudDownload size={13} />}
            {t('settings.filamentSync.pullNow')}
          </button>
        )}
        {(syncStatus.direction === 'push' || syncStatus.direction === 'bidirectional') && (
          <button
            onClick={() => { setLastResult(null); pushMut.mutate() }}
            disabled={busy}
            className="btn-secondary flex items-center gap-1.5 text-xs"
          >
            {pushMut.isPending
              ? <RefreshCw size={13} className="animate-spin" />
              : <CloudUpload size={13} />}
            {t('settings.filamentSync.pushNow')}
          </button>
        )}
      </div>

      {/* Last result */}
      {lastResult && (
        <div className={`flex items-start gap-2 text-xs rounded px-3 py-2 ${
          lastResult.errors > 0
            ? 'bg-yellow-900/20 border border-yellow-800 text-yellow-400'
            : 'bg-green-900/20 border border-green-800 text-green-400'
        }`}>
          {lastResult.errors > 0
            ? <AlertCircle size={13} className="mt-0.5 shrink-0" />
            : <CheckCircle size={13} className="mt-0.5 shrink-0" />}
          <span>
            {t('settings.filamentSync.result', {
              op: t(`settings.filamentSync.op_${lastResult.op}`),
              created: lastResult.created,
              updated: lastResult.updated,
              unchanged: lastResult.unchanged,
              errors: lastResult.errors,
            })}
          </span>
        </div>
      )}

      {/* Mutation errors */}
      {(pullMut.isError || pushMut.isError) && (
        <div className="flex items-start gap-2 text-xs text-red-400">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span>{String((pullMut.error || pushMut.error) instanceof Error
            ? (pullMut.error || pushMut.error as Error).message
            : pullMut.error || pushMut.error)}</span>
        </div>
      )}
    </div>
  )
}
