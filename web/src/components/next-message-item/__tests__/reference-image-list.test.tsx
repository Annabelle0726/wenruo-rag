import { render, screen } from '@testing-library/react';
import { ReferenceImageList } from '../reference-image-list';

// The reference carousel used to pick images by the wrong pool slot: the answer's
// citation markers are 1-based ("ID: 1" … "ID: n" from kb_prompt) but the list
// compared them against 0-based array indexes, so a five-chunk pool rendered
// nothing at all while the answer showed a phantom "图 6".
jest.mock('@/components/image', () => ({
  __esModule: true,
  default: ({ id, label }: { id: string; label?: string }) => (
    <div data-testid="doc-image" data-id={id} data-label={label ?? ''} />
  ),
  // The component also resolves a blob URL for the photo viewer; the mapping
  // under test is the label/id pair, so no fetch is exercised here.
  useDocumentImageUrl: () => '',
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

jest.mock('@/components/ui/carousel', () => ({
  __esModule: true,
  Carousel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CarouselContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CarouselItem: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CarouselPrevious: () => null,
  CarouselNext: () => null,
}));

jest.mock('react-photo-view', () => ({
  __esModule: true,
  PhotoProvider: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  PhotoView: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const referenceChunks = Array.from({ length: 5 }, (_, index) => ({
  id: `chunk-${index + 1}`,
  image_id: `kb-${index + 1}`,
  doc_type: 'table',
})) as never;

describe('ReferenceImageList citation mapping', () => {
  it('renders the image of the cited chunk and labels it with the citation number', () => {
    render(
      <ReferenceImageList
        referenceChunks={referenceChunks}
        messageContent="老化前抗张强度为 10.0 N/mm² [ID:5]。"
      />,
    );

    const images = screen.getAllByTestId('doc-image');
    expect(images).toHaveLength(1);
    // [ID:5] is the fifth chunk, i.e. index 4 of the pool. The badge repeats the
    // marker verbatim so a reader can match it to the `[5]` in the answer.
    expect(images[0].dataset.id).toBe('kb-5');
    expect(images[0].dataset.label).toBe('[5]');
  });

  it('maps the first citation to the first chunk', () => {
    render(
      <ReferenceImageList
        referenceChunks={referenceChunks}
        messageContent="见表1 [ID:1]。"
      />,
    );

    const images = screen.getAllByTestId('doc-image');
    expect(images).toHaveLength(1);
    expect(images[0].dataset.id).toBe('kb-1');
    expect(images[0].dataset.label).toBe('[1]');
  });

  it('renders nothing for a marker outside the pool instead of a phantom figure', () => {
    const { container } = render(
      <ReferenceImageList
        referenceChunks={referenceChunks}
        messageContent="不存在的引用 [ID:6]。"
      />,
    );

    expect(screen.queryAllByTestId('doc-image')).toHaveLength(0);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for marker 0, which 1-based citations never emit', () => {
    const { container } = render(
      <ReferenceImageList
        referenceChunks={referenceChunks}
        messageContent="无效引用 [ID:0]。"
      />,
    );

    expect(screen.queryAllByTestId('doc-image')).toHaveLength(0);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing while the pool is still empty', () => {
    // The backend sends the reference with the final event only, so mid-stream
    // no marker resolves and no figure — let alone `图 NaN` — may appear.
    const { container } = render(
      <ReferenceImageList
        referenceChunks={[] as never}
        messageContent="护套为 PUR 紫色 [ID:1]。"
      />,
    );

    expect(screen.queryAllByTestId('doc-image')).toHaveLength(0);
    expect(container).toBeEmptyDOMElement();
    expect(container.textContent).not.toContain('NaN');
  });

  it('keeps the resolvable figures when one marker is unusable', () => {
    const { container } = render(
      <ReferenceImageList
        referenceChunks={referenceChunks}
        messageContent="无效引用 [ID:0]，见表 [ID:5]。"
      />,
    );

    const images = screen.getAllByTestId('doc-image');
    expect(images).toHaveLength(1);
    expect(images[0].dataset.id).toBe('kb-5');
    expect(images[0].dataset.label).toBe('[5]');
    expect(container.textContent).not.toContain('NaN');
  });
});
