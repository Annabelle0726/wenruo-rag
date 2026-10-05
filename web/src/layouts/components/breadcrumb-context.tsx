import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

/**
 * One level of the global breadcrumb.
 *
 * `label` is already translated: the page that knows the entity name also owns
 * the copy, so the bar never has to know which module a label came from. `to` is
 * omitted on the level the operator is standing on — that last level is not a
 * link.
 */
export type BreadcrumbCrumb = {
  label: string;
  to?: string;
};

type BreadcrumbTrailValue = {
  /** The entity-bound levels published by the page below the bar. */
  entityTrail: BreadcrumbCrumb[];
  claim: (crumbs: BreadcrumbCrumb[], token: symbol) => void;
  release: (token: symbol) => void;
};

const BreadcrumbTrailContext = createContext<BreadcrumbTrailValue | null>(null);

/**
 * The trail is published by pages, not resolved by the bar.
 *
 * The bar sits in the layout, above the route element, so it cannot read a
 * dataset's name out of `KnowledgeBaseProvider` or a chat's out of
 * `useFetchChat` without re-running every module's query on every route. Instead
 * each page pushes the levels it already holds — the knowledge base's name, the
 * assistant's, the open session's — into this one store, and the bar joins them
 * with the levels it can derive from the path alone.
 *
 * Every claim carries a token so a page that is being replaced cannot clear the
 * trail its successor has already published: the unmount cleanup only empties the
 * store while that page is still its owner.
 */
export function BreadcrumbTrailProvider({ children }: React.PropsWithChildren) {
  const [trail, setTrail] = useState<{
    token: symbol | null;
    crumbs: BreadcrumbCrumb[];
  }>({ token: null, crumbs: [] });

  const claim = useCallback((crumbs: BreadcrumbCrumb[], token: symbol) => {
    setTrail({ token, crumbs });
  }, []);

  const release = useCallback((token: symbol) => {
    setTrail((previous) =>
      previous.token === token ? { token: null, crumbs: [] } : previous,
    );
  }, []);

  const value = useMemo(
    () => ({ entityTrail: trail.crumbs, claim, release }),
    [trail.crumbs, claim, release],
  );

  return (
    <BreadcrumbTrailContext.Provider value={value}>
      {children}
    </BreadcrumbTrailContext.Provider>
  );
}

/** Read by the breadcrumb bar. Falls back to no entity level outside the shell. */
export function useBreadcrumbEntityTrail(): BreadcrumbCrumb[] {
  return useContext(BreadcrumbTrailContext)?.entityTrail ?? [];
}

/**
 * Publish the page's own breadcrumb levels — everything between the module and
 * the page itself, in order. A knowledge base page publishes its name, a chat
 * page its assistant and its open conversation.
 *
 * The array is rebuilt on every render by the caller, so the effect keys off a
 * text digest of it rather than its identity.
 */
export function usePublishBreadcrumbTrail(crumbs: BreadcrumbCrumb[]) {
  const context = useContext(BreadcrumbTrailContext);
  const claim = context?.claim;
  const release = context?.release;

  const digest = crumbs
    .map((crumb) => `${crumb.label}\u0000${crumb.to ?? ''}`)
    .join('\u0001');

  useEffect(() => {
    if (!claim || !release) {
      return;
    }

    const token = Symbol('breadcrumb-trail');
    claim(crumbs, token);

    return () => release(token);
    // `digest` is the stable identity of `crumbs`; depending on the array itself
    // would republish on every render.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [digest, claim, release]);
}

/**
 * The same publish, for a page that owns its own shell.
 *
 * `/chat/:id` renders `RootLayoutContainer` itself, so its hook call site sits
 * above the provider it creates. Returning a component instead lets that page put
 * the publish inside the shell, where the context is visible.
 */
export function BreadcrumbTrail({ crumbs }: { crumbs: BreadcrumbCrumb[] }) {
  usePublishBreadcrumbTrail(crumbs);

  return null;
}
