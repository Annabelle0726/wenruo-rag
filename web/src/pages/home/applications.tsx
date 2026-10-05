import { CeramicSegmented, CeramicSegmentedValue } from '@/components/ceramic-segmented';
import { EmptyCardType } from '@/components/empty/constant';
import { EmptyAppCard } from '@/components/empty/empty';
import { Routes } from '@/routes';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Agents } from './agent-list';
import { SeeAllAppCard } from './application-card';
import { ChatList } from './chat-list';
import { HomeCardGrid, SectionHeading } from './home-layout';
import { MemoryList } from './memory-list';
import { SearchList } from './search-list';

const IconMap = {
  [Routes.Chats]: 'chats',
  [Routes.Searches]: 'searches',
  [Routes.Agents]: 'agents',
  [Routes.Memories]: 'memory',
};

const EmptyTypeMap = {
  [Routes.Chats]: EmptyCardType.Chat,
  [Routes.Searches]: EmptyCardType.Search,
  [Routes.Agents]: EmptyCardType.Agent,
  [Routes.Memories]: EmptyCardType.Memory,
};

export function Applications() {
  const [val, setVal] = useState(Routes.Chats);
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [listLength, setListLength] = useState(0);
  const [loading, setLoading] = useState(false);

  const handleNavigate = useCallback(
    ({ isCreate }: { isCreate?: boolean }) => {
      if (isCreate) {
        navigate(val + '?isCreate=true');
      } else {
        navigate(val);
      }
    },
    [navigate, val],
  );

  const options = useMemo(
    () => [
      { value: Routes.Chats, label: t('header.chat') },
      { value: Routes.Searches, label: t('header.search') },
      { value: Routes.Agents, label: t('header.flow') },
      { value: Routes.Memories, label: t('header.memories') },
    ],
    [t],
  );

  // Only the tab changes here. The previous tab's cells stay on screen while the
  // new list loads: clearing the count and flagging a load collapsed the grid to
  // an empty row for a frame and then grew it back, which is what made the section
  // jump every time the switcher was clicked.
  const handleChange = (path: CeramicSegmentedValue) => {
    setVal(path as Routes);
  };

  return (
    // The gap above the divider is deliberately smaller than it was: it stacks on
    // top of the knowledge-base grid's own 24px filler, so 48px of margin plus
    // 40px of padding left a hole under the last knowledge-base row.
    <section className="mt-8 border-t border-cable-divider pt-8">
      {/* The heading and the tab control live outside the panel below, so a tab
          switch only swaps the panel's contents: the nav never unmounts and its
          highlight never flickers. */}
      <SectionHeading
        iconName={IconMap[val as keyof typeof IconMap]}
        label={options.find((x) => x.value === val)?.label ?? ''}
      >
        <CeramicSegmented
          options={options}
          value={val}
          onChange={handleChange}
        />
      </SectionHeading>

      {/* Keyed on the active tab so the new panel fades in. The grid's rows are
          sized by `HomeCardGrid`, so this floor is only the empty case: it keeps a
          single row for the tab that has nothing to show yet. */}
      <HomeCardGrid
        key={val}
        className="min-h-[112px] animate-in fade-in-0 duration-200"
      >
        {val === Routes.Agents && (
          <Agents
            setListLength={(length: number) => setListLength(length)}
            setLoading={(loading: boolean) => setLoading(loading)}
          />
        )}
        {val === Routes.Chats && (
          <ChatList
            setListLength={(length: number) => setListLength(length)}
            setLoading={(loading: boolean) => setLoading(loading)}
          />
        )}
        {val === Routes.Searches && (
          <SearchList
            setListLength={(length: number) => setListLength(length)}
            setLoading={(loading: boolean) => setLoading(loading)}
          />
        )}
        {val === Routes.Memories && (
          <MemoryList
            setListLength={(length: number) => setListLength(length)}
            setLoading={(loading: boolean) => setLoading(loading)}
          />
        )}
        {listLength > 0 && (
          <SeeAllAppCard click={() => handleNavigate({ isCreate: false })} />
        )}

        {/* The create tile is a grid item like the tiles it stands in for, so it
            matches them in width and height instead of sitting in a 210px box of
            its own. */}
        {listLength <= 0 && !loading && (
          <EmptyAppCard
            type={EmptyTypeMap[val as keyof typeof EmptyTypeMap]}
            onClick={() => handleNavigate({ isCreate: true })}
          />
        )}
      </HomeCardGrid>
    </section>
  );
}
