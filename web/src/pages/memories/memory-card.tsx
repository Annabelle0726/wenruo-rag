import { CardIdentityIcon } from '@/components/card-identity-icon';
import { HomeCard } from '@/components/home-card';
import { MoreButton } from '@/components/more-button';
import { SharedBadge } from '@/components/shared-badge';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { useTranslation } from 'react-i18next';
import { MemoryOptions } from './constants';
import { IMemory } from './interface';
import { MemoryDropdown } from './memory-dropdown';

interface IProps {
  data: IMemory;
  showMemoryRenameModal: (data: IMemory) => void;
}
export function MemoryCard({ data, showMemoryRenameModal }: IProps) {
  const { navigateToMemory } = useNavigatePage();
  const { t } = useTranslation();
  const selectedTypes = MemoryOptions(t).filter((option) =>
    (data?.memory_type ?? []).includes(option.value),
  );
  const visibleTypes = selectedTypes.slice(0, 2);

  return (
    <HomeCard
      layout="memory"
      className="relative before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-transparent before:content-[''] hover:before:bg-cable-brand"
      data={{
        name: data?.name,
        description: data?.description,
        update_time: data?.create_time,
      }}
      leading={<CardIdentityIcon kind="memory" avatar={data?.avatar} />}
      extra={
        selectedTypes.length > 0 ? (
          <div
            className="flex h-4 min-w-0 items-center gap-1 overflow-hidden"
            title={selectedTypes.map((type) => type.label).join(' · ')}
          >
            {visibleTypes.map((type) => (
              <span
                key={type.value}
                className="inline-flex h-4 max-w-24 shrink-0 items-center truncate rounded-sm border border-cable-hairline bg-bg-input/70 px-1 text-[10px] leading-none text-text-secondary"
              >
                {type.label}
              </span>
            ))}
            {selectedTypes.length > visibleTypes.length && (
              <span className="inline-flex h-4 shrink-0 items-center rounded-sm border border-cable-hairline bg-bg-input/70 px-1 text-[10px] leading-none tabular-nums text-text-secondary">
                +{selectedTypes.length - visibleTypes.length}
              </span>
            )}
          </div>
        ) : null
      }
      moreDropdown={
        <MemoryDropdown
          memory={data}
          showMemoryRenameModal={showMemoryRenameModal}
        >
          <MoreButton></MoreButton>
        </MemoryDropdown>
      }
      sharedBadge={<SharedBadge>{data?.owner_name}</SharedBadge>}
      onClick={navigateToMemory(data?.id)}
    />
  );
}
