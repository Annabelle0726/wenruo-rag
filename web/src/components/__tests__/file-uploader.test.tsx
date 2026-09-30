import { render, screen } from '@testing-library/react';
import { FileUploader } from '@/components/file-uploader';

/**
 * Uploading a folder is not available, so the uploader must not offer it.
 *
 * The capability is kept behind `showFolderTab` (the hidden `webkitdirectory`
 * input, `processFiles`, and the `{ path, file }` shape the upload pipeline
 * accepts all still work) - what these pin is that no product entry renders it by
 * default, and that the file entry, the drag-and-drop area and the file input are
 * all still there.
 */
describe('FileUploader entry points', () => {
  it('offers the file entry and no folder entry', () => {
    render(<FileUploader />);

    expect(screen.getByRole('tab', { name: /文件|Files/ })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /文件夹|Folder/ })).toBeNull();
    expect(document.querySelector('input[webkitdirectory]')).toBeNull();
    // Drag-and-drop and click-to-pick are the same drop zone, and it keeps its own
    // file input.
    expect(document.querySelector('input[type="file"]')).not.toBeNull();
  });

  it('still renders the folder entry for a caller that asks for it', () => {
    // Not dead code: the switch is the capability, and this is what it does. The
    // folder TAB is the entry point - its drop zone and the hidden
    // `webkitdirectory` input inside it only mount once that tab is selected, which
    // is why the default case above checks for the tab and the input both.
    render(<FileUploader showFolderTab />);

    expect(
      screen.getByRole('tab', { name: /文件夹|Folder/ }),
    ).toBeInTheDocument();
  });
});
