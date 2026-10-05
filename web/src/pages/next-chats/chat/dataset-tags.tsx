import { Button } from '@/components/ui/button';
import { IDataset } from '@/interfaces/database/dataset';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/**
 * Beyond this many datasets the row summarises instead of shrinking the
 * conversation title out of the way; the count re-opens the settings drawer,
 * which lists every one of them.
 */
const MaxVisibleDatasetTags = 3;

/** One tag: the dataset the settings drawer re-opens on, and the name it shows. */
export type DatasetTag = {
  id: string;
  label: string;
};

/**
 * Names the conversation's effective dataset ids.
 *
 * Resolved by the page rather than here: this row is a leaf of the header, and
 * looking the ids up itself would drag the dataset request — and the app router
 * built behind it — into every consumer of a presentational component.
 *
 * A dataset that was deleted after it was bound comes back missing; its tag
 * then falls back to the raw id, so a binding is never invisible (and never
 * unchangeable) just because its dataset is gone.
 */
export function resolveDatasetTags(
  datasetIds: string[],
  datasets?: IDataset[],
): DatasetTag[] {
  const nameById = new Map(
    (datasets ?? []).map((dataset) => [dataset.id, dataset.name]),
  );

  return datasetIds.map((id) => ({ id, label: nameById.get(id) ?? id }));
}

type DatasetTagsProps = {
  /**
   * The conversation's effective datasets: its own binding when it has one,
   * otherwise the assistant's set.
   */
  datasets: DatasetTag[];
  /** Opens the chat settings drawer, where the selection is changed. */
  onOpenSettings: () => void;
};

/**
 * The datasets the open conversation retrieves from.
 *
 * The header row is a fixed height shared with the title and the controls, so
 * the tags are capped and each one truncates; the settings drawer behind them
 * is what shows the full selection, and it is the same panel the gear opens.
 */
export function DatasetTags({ datasets, onOpenSettings }: DatasetTagsProps) {
  const { t } = useTranslation();

  if (datasets.length === 0) {
    return null;
  }

  const visibleTags = datasets.slice(0, MaxVisibleDatasetTags);
  const hiddenCount = datasets.length - visibleTags.length;

  return (
    <div
      className="flex min-w-0 shrink items-center gap-1 overflow-hidden"
      aria-label={t('chat.sessionDatasets')}
      data-testid="chat-detail-dataset-tags"
    >
      {visibleTags.map((tag) => (
        <DatasetTagButton
          key={tag.id}
          label={tag.label}
          datasetId={tag.id}
          onClick={onOpenSettings}
        />
      ))}

      {hiddenCount > 0 && (
        <DatasetTagButton
          label={`+${hiddenCount}`}
          datasetId="overflow"
          onClick={onOpenSettings}
        />
      )}
    </div>
  );
}

function DatasetTagButton({
  label,
  datasetId,
  onClick,
}: {
  label: string;
  datasetId: string;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      // The tags name the conversation's retrieval scope, so they are buttons
      // in the row rather than decoration: a click opens the settings drawer,
      // which is where the selection is changed.
      className={cn(
        'h-6 max-w-[9rem] shrink-0 rounded-full border border-cable-hairline px-2 text-xs',
        'text-text-secondary hover:bg-cable-brand-soft hover:text-cable-brand',
      )}
      title={label}
      onClick={onClick}
      data-testid="chat-detail-dataset-tag"
      data-dataset-id={datasetId}
    >
      <span className="truncate">{label}</span>
    </Button>
  );
}
