import { CardIdentityIcon } from '@/components/card-identity-icon';
import { HomeCard } from '@/components/home-card';
import { MoreButton } from '@/components/more-button';
import { SharedBadge } from '@/components/shared-badge';
import { useNavigatePage } from '@/hooks/logic-hooks/navigate-hooks';
import { useTranslation } from 'react-i18next';
import { IMemory } from './interface';
import { MemoryDropdown } from './memory-dropdown';

interface IProps {
  data: IMemory;
  showMemoryRenameModal: (data: IMemory) => void;
}
export function MemoryCard({ data, showMemoryRenameModal }: IProps) {
  const { navigateToMemory } = useNavigatePage();
  const { t } = useTranslation();

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
        <span className="inline-flex h-5 shrink-0 items-center rounded border border-cable-hairline bg-cable-brand/10 px-1.5 text-[11px] font-medium leading-none text-cable-brand">
          {t('memories.raw')}
        </span>
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
