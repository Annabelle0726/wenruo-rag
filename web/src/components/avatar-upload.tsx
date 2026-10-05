/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import { combineRefs } from '@/lib/utils';
import { transformFile2Base64 } from '@/utils/file-util';
import {
  LucidePencil,
  LucidePlus,
  LucideX,
  LucideZoomIn,
  LucideZoomOut,
} from 'lucide-react';
import message from './ui/message';
import {
  ChangeEventHandler,
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Avatar, AvatarFallback, AvatarImage } from './ui/avatar';
import { Button } from './ui/button';
import { Modal } from './ui/modal/modal';

// Maximum size of the image file selected for an avatar, in bytes (4 MB).
const MaxAvatarFileSize = 4 * 1024 * 1024;

type AvatarUploadProps = {
  value?: string;
  onChange?: (value: string) => void;
  tips?: string;
  uploadInputTestId?: string;
  removeButtonTestId?: string;
  cropModalTestId?: string;
  cropModalOkButtonTestId?: string;
};

type DragMode = 'move' | 'nw' | 'ne' | 'sw' | 'se' | null;

export const AvatarUpload = forwardRef<HTMLInputElement, AvatarUploadProps>(
  function AvatarUpload(
    {
      value,
      onChange,
      tips,
      uploadInputTestId,
      removeButtonTestId,
      cropModalTestId,
      cropModalOkButtonTestId,
    },
    ref,
  ) {
    const { t } = useTranslation();
    const [avatarBase64Str, setAvatarBase64Str] = useState('');
    const [isCropModalOpen, setIsCropModalOpen] = useState(false);
    const [imageToCrop, setImageToCrop] = useState<string | null>(null);
    const [cropArea, setCropArea] = useState({ x: 0, y: 0, size: 200 });
    const innerInputRef = useRef<HTMLInputElement | null>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // 拖拽与缩放状态
    const isDraggingRef = useRef(false);
    const dragModeRef = useRef<DragMode>(null);
    const dragStartRef = useRef({
      mouseX: 0,
      mouseY: 0,
      cropX: 0,
      cropY: 0,
      cropSize: 200,
    });

    // 性能优化：用于拖拽时的帧率同步句柄
    const rafIdRef = useRef<number | null>(null);

    const [imageScale, setImageScale] = useState(1);
    const [imageOffset, setImageOffset] = useState({ x: 0, y: 0 });

    const handleChange: ChangeEventHandler<HTMLInputElement> = useCallback(
      async (ev) => {
        const file = ev.target?.files?.[0];
        if (/\.(jpg|jpeg|png|webp|bmp)$/i.test(file?.name ?? '')) {
          if (file!.size > MaxAvatarFileSize) {
            message.error(t('knowledgeConfiguration.photoTip'));
            ev.target.value = '';
            return;
          }
          // 此处可调小边长限制（如 800）来进一步提升大图剪裁效率
          const str = await transformFile2Base64(file!, 800);
          setImageToCrop(str);
          setIsCropModalOpen(true);
        }
        ev.target.value = '';
      },
      [t],
    );

    const handleRemove = useCallback(() => {
      setAvatarBase64Str('');
      onChange?.('');
    }, [onChange]);

    const handleCrop = useCallback(() => {
      if (!imageRef.current || !canvasRef.current) return;

      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      const image = imageRef.current;

      if (!ctx) return;

      canvas.width = 64;
      canvas.height = 64;

      ctx.drawImage(
        image,
        cropArea.x,
        cropArea.y,
        cropArea.size,
        cropArea.size,
        0,
        0,
        64,
        64,
      );

      const croppedImageBase64 = canvas.toDataURL('image/png');
      setAvatarBase64Str(croppedImageBase64);
      onChange?.(croppedImageBase64);
      setIsCropModalOpen(false);
    }, [cropArea, onChange]);

    const handleCancelCrop = useCallback(() => {
      setIsCropModalOpen(false);
      setImageToCrop(null);
    }, []);

    const initCropArea = useCallback(() => {
      if (!imageRef.current || !containerRef.current) return;

      const image = imageRef.current;
      const container = containerRef.current;

      const scale = Math.min(
        container.clientWidth / image.width,
        container.clientHeight / image.height,
      );
      setImageScale(scale);

      const scaledWidth = image.width * scale;
      const scaledHeight = image.height * scale;
      const offsetX = (container.clientWidth - scaledWidth) / 2;
      const offsetY = (container.clientHeight - scaledHeight) / 2;
      setImageOffset({ x: offsetX, y: offsetY });

      const size = Math.min(scaledWidth, scaledHeight) * 0.75;
      const x = (image.width - size / scale) / 2;
      const y = (image.height - size / scale) / 2;

      setCropArea({ x, y, size: size / scale });
    }, []);

    // 缩放计算函数
    const updateCropSize = useCallback((newSize: number) => {
      if (!imageRef.current) return;
      const image = imageRef.current;
      const maxAllowedSize = Math.min(image.width, image.height);
      const minAllowedSize = 30;

      const boundedSize = Math.max(
        minAllowedSize,
        Math.min(newSize, maxAllowedSize),
      );

      setCropArea((prev) => {
        const centerRatioX = (prev.x + prev.size / 2) / image.width;
        const centerRatioY = (prev.y + prev.size / 2) / image.height;

        const newX = centerRatioX * image.width - boundedSize / 2;
        const newY = centerRatioY * image.height - boundedSize / 2;

        const boundedX = Math.max(0, Math.min(newX, image.width - boundedSize));
        const boundedY = Math.max(
          0,
          Math.min(newY, image.height - boundedSize),
        );

        return {
          x: boundedX,
          y: boundedY,
          size: boundedSize,
        };
      });
    }, []);

    // 鼠标移动核心逻辑（增加 requestAnimationFrame 渲染防抖）
    const handleMouseMove = useCallback(
      (e: MouseEvent) => {
        if (!isDraggingRef.current || !imageRef.current) return;

        if (rafIdRef.current) {
          cancelAnimationFrame(rafIdRef.current);
        }

        const clientX = e.clientX;
        const clientY = e.clientY;

        rafIdRef.current = requestAnimationFrame(() => {
          if (!imageRef.current) return;
          const image = imageRef.current;
          const mode = dragModeRef.current;
          const { mouseX, mouseY, cropX, cropY, cropSize } = dragStartRef.current;

          const deltaX = (clientX - mouseX) / imageScale;
          const deltaY = (clientY - mouseY) / imageScale;

          if (mode === 'move') {
            let newX = cropX + deltaX;
            let newY = cropY + deltaY;

            newX = Math.max(0, Math.min(newX, image.width - cropSize));
            newY = Math.max(0, Math.min(newY, image.height - cropSize));

            setCropArea({ x: newX, y: newY, size: cropSize });
          } else {
            const currentMouseX = cropX + deltaX;
            const currentMouseY = cropY + deltaY;

            let newX = cropX;
            let newY = cropY;
            let newSize = cropSize;

            if (mode === 'se') {
              const dx = currentMouseX - cropX;
              const dy = currentMouseY - cropY;
              const rawSize = Math.max(dx, dy);
              const maxAllowed = Math.min(image.width - cropX, image.height - cropY);
              newSize = Math.max(30, Math.min(rawSize, maxAllowed));
              newX = cropX;
              newY = cropY;
            } else if (mode === 'nw') {
              const anchorX = cropX + cropSize;
              const anchorY = cropY + cropSize;
              const dx = anchorX - currentMouseX;
              const dy = anchorY - currentMouseY;
              const rawSize = Math.max(dx, dy);
              const maxAllowed = Math.min(anchorX, anchorY);
              newSize = Math.max(30, Math.min(rawSize, maxAllowed));
              newX = anchorX - newSize;
              newY = anchorY - newSize;
            } else if (mode === 'ne') {
              const anchorX = cropX;
              const anchorY = cropY + cropSize;
              const dx = currentMouseX - anchorX;
              const dy = anchorY - currentMouseY;
              const rawSize = Math.max(dx, dy);
              const maxAllowed = Math.min(image.width - anchorX, anchorY);
              newSize = Math.max(30, Math.min(rawSize, maxAllowed));
              newX = anchorX;
              newY = anchorY - newSize;
            } else if (mode === 'sw') {
              const anchorX = cropX + cropSize;
              const anchorY = cropY;
              const dx = anchorX - currentMouseX;
              const dy = currentMouseY - anchorY;
              const rawSize = Math.max(dx, dy);
              const maxAllowed = Math.min(anchorX, image.height - anchorY);
              newSize = Math.max(30, Math.min(rawSize, maxAllowed));
              newX = anchorX - newSize;
              newY = anchorY;
            }

            setCropArea({ x: newX, y: newY, size: newSize });
          }
        });
      },
      [imageScale],
    );

    const handleMouseUp = useCallback(() => {
      isDraggingRef.current = false;
      dragModeRef.current = null;
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    }, [handleMouseMove]);

    const handleMouseDown = useCallback(
      (e: React.MouseEvent, mode: DragMode) => {
        e.preventDefault();
        e.stopPropagation();
        isDraggingRef.current = true;
        dragModeRef.current = mode;
        dragStartRef.current = {
          mouseX: e.clientX,
          mouseY: e.clientY,
          cropX: cropArea.x,
          cropY: cropArea.y,
          cropSize: cropArea.size,
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
      },
      [cropArea, handleMouseMove, handleMouseUp],
    );

    const handleWheel = useCallback(
      (e: React.WheelEvent) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        updateCropSize(cropArea.size * delta);
      },
      [cropArea.size, updateCropSize],
    );

    useEffect(() => {
      if (value) {
        setAvatarBase64Str(value);
      }
    }, [value]);

    const maxCropSize = imageRef.current
      ? Math.min(imageRef.current.width, imageRef.current.height)
      : 300;

    return (
      <div className="flex justify-start items-end space-x-2">
        <div className="relative group">
          <input
            placeholder=""
            type="file"
            title=""
            accept="image/*"
            className="peer/input size-0 absolute top-0 left-0 opacity-0 pointer-events-none"
            onChange={handleChange}
            ref={combineRefs(ref, innerInputRef)}
            data-testid={uploadInputTestId}
            tabIndex={-1}
          />

          {!avatarBase64Str ? (
            <Button
              variant="dashed"
              size="icon"
              className="ceramic-rail size-16 flex flex-col items-center gap-1 rounded-xl border border-[var(--badge-border)] hover:shadow-accent-glow"
              type="button"
              onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                e.stopPropagation();
                innerInputRef.current?.click();
              }}
            >
              <LucidePlus className="size-4" />
              <span>{t('common.upload')}</span>
            </Button>
          ) : (
            <div className="size-16 relative grid place-content-center">
              <Button
                variant="transparent"
                size="icon"
                type="button"
                className="ceramic-rail group/button size-full gap-0 overflow-hidden rounded-xl border border-[var(--badge-border)] p-0 transition-shadow relative hover:shadow-accent-glow"
                onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                  e.stopPropagation();
                  innerInputRef.current?.click();
                }}
              >
                <Avatar className="size-full rounded-none">
                  <AvatarImage className="block" src={avatarBase64Str} alt="" />
                  <AvatarFallback />
                </Avatar>

                <div
                  className="
                  absolute inset-0 flex items-center justify-center
                  bg-black/40 opacity-0 transition-opacity
                  group-hover/button:opacity-100 group-focus-visible/button:opacity-100"
                >
                  <LucidePencil className="size-5 opacity-75" />
                </div>
              </Button>

              <Button
                onClick={handleRemove}
                size="icon"
                className="border-background focus-visible:border-background absolute -top-2 -right-2 size-6 rounded-full border-2 shadow-none z-10"
                aria-label="Remove image"
                type="button"
                data-testid={removeButtonTestId}
              >
                <LucideX className="size-3" />
              </Button>
            </div>
          )}
        </div>

        <div className="ms-1 text-xs text-text-secondary">
          {tips ?? t('knowledgeConfiguration.photoTip')}
        </div>

        {/* Crop Modal */}
        <Modal
          open={isCropModalOpen}
          onOpenChange={(open) => {
            setIsCropModalOpen(open);
            if (!open) {
              setImageToCrop(null);
            }
          }}
          title={t('setting.cropImage')}
          size="small"
          onCancel={handleCancelCrop}
          onOk={handleCrop}
          testId={cropModalTestId}
          okButtonTestId={cropModalOkButtonTestId}
          footer={
            <div className="flex items-center justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={handleCancelCrop}
                className="px-4 py-1.5 text-sm font-medium text-text-secondary hover:text-text-primary bg-transparent hover:bg-white/5 border border-border/80 rounded-lg transition-all duration-200 focus-visible:outline-none"
              >
                {t('common.cancel')}
              </Button>
              <Button
                type="button"
                onClick={handleCrop}
                data-testid={cropModalOkButtonTestId}
                className="px-5 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg shadow-md shadow-blue-600/20 hover:shadow-blue-500/35 transition-all duration-200 active:scale-95 focus-visible:outline-none"
              >
                {t('common.confirm')}
              </Button>
            </div>
          }
        >
          <div className="flex flex-col items-center p-4">
            {imageToCrop && (
              <div className="w-full flex flex-col items-center">
                <div
                  ref={containerRef}
                  className="relative overflow-hidden border border-border rounded-md bg-bg-card select-none"
                  style={{
                    width: '300px',
                    height: '300px',
                    touchAction: 'none',
                  }}
                  onWheel={handleWheel}
                >
                  <img
                    ref={imageRef}
                    src={imageToCrop}
                    alt="To crop"
                    className="absolute block pointer-events-none"
                    style={{
                      transform: `scale(${imageScale})`,
                      transformOrigin: 'top left',
                      left: `${imageOffset.x}px`,
                      top: `${imageOffset.y}px`,
                    }}
                    onLoad={initCropArea}
                  />
                  {imageRef.current && (
                    <div
                      className="absolute border-2 border-white border-dashed cursor-move"
                      style={{
                        left: `${imageOffset.x + cropArea.x * imageScale}px`,
                        top: `${imageOffset.y + cropArea.y * imageScale}px`,
                        width: `${cropArea.size * imageScale}px`,
                        height: `${cropArea.size * imageScale}px`,
                        // 用高效的 outline 替代极其吃 GPU 性能的 boxShadow 9999px
                        outline: '9999px solid rgba(0, 0, 0, 0.5)',
                        willChange: 'left, top, width, height',
                      }}
                      onMouseDown={(e) => handleMouseDown(e, 'move')}
                    >
                      {/* 四角拉伸手柄 */}
                      <div
                        className="absolute -top-1.5 -left-1.5 size-3 bg-blue-500 border-2 border-white rounded-full cursor-nwse-resize z-20"
                        onMouseDown={(e) => handleMouseDown(e, 'nw')}
                      />
                      <div
                        className="absolute -top-1.5 -right-1.5 size-3 bg-blue-500 border-2 border-white rounded-full cursor-nesw-resize z-20"
                        onMouseDown={(e) => handleMouseDown(e, 'ne')}
                      />
                      <div
                        className="absolute -bottom-1.5 -left-1.5 size-3 bg-blue-500 border-2 border-white rounded-full cursor-nesw-resize z-20"
                        onMouseDown={(e) => handleMouseDown(e, 'sw')}
                      />
                      <div
                        className="absolute -bottom-1.5 -right-1.5 size-3 bg-blue-500 border-2 border-white rounded-full cursor-nwse-resize z-20"
                        onMouseDown={(e) => handleMouseDown(e, 'se')}
                      />
                    </div>
                  )}
                </div>

                {/* 底部滑动条与快捷按钮 */}
                <div className="flex items-center justify-center gap-3 mt-4 w-[300px]">
                  <button
                    type="button"
                    onClick={() => updateCropSize(cropArea.size * 0.85)}
                    className="text-text-secondary hover:text-text-primary p-1 rounded transition-colors"
                    title="缩小"
                  >
                    <LucideZoomOut className="size-4" />
                  </button>
                  <input
                    type="range"
                    min={30}
                    max={maxCropSize}
                    value={cropArea.size}
                    onChange={(e) => updateCropSize(Number(e.target.value))}
                    className="w-full accent-blue-500 h-1.5 bg-slate-700/60 rounded-lg appearance-none cursor-pointer"
                  />
                  <button
                    type="button"
                    onClick={() => updateCropSize(cropArea.size * 1.15)}
                    className="text-text-secondary hover:text-text-primary p-1 rounded transition-colors"
                    title="放大"
                  >
                    <LucideZoomIn className="size-4" />
                  </button>
                </div>

                <div className="flex justify-center mt-2">
                  <p className="text-xs text-text-secondary">
                    {t('setting.cropTip')}
                  </p>
                </div>
                <canvas ref={canvasRef} className="hidden" />
              </div>
            )}
          </div>
        </Modal>
      </div>
    );
  },
);