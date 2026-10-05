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

import { Authorization } from '@/constants/authorization';
import { restAPIv1 } from '@/utils/api';
import { getAuthorization } from '@/utils/authorization-util';
import classNames from 'classnames';
import { ImageOff } from 'lucide-react';
import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover';

interface IImage extends React.ImgHTMLAttributes<HTMLImageElement> {
  id: string;
  t?: string | number;
  label?: string;
}

type ImageCacheItem = {
  count: number;
  objectUrl?: string;
  promise?: Promise<string>;
  timer?: ReturnType<typeof setTimeout>;
};

const imageCache = new Map<string, ImageCacheItem>();

export const buildDocumentImageUrl = (id: string, t?: string | number) => {
  const params = new URLSearchParams();

  if (t) {
    params.set('_t', String(t));
  }

  const query = params.toString();
  return `${restAPIv1}/documents/images/${id}${query ? `?${query}` : ''}`;
};

const fetchDocumentImage = (url: string, authorization: string) => {
  const cacheKey = `${authorization}:${url}`;
  let item = imageCache.get(cacheKey);

  if (!item) {
    item = { count: 0 };
    imageCache.set(cacheKey, item);
  }
  if (item.timer) {
    clearTimeout(item.timer);
    item.timer = undefined;
  }
  item.count += 1;

  if (!item.promise) {
    item.promise = fetch(url, {
      // Same-origin so the session cookie travels with the request. This app
      // logs in with a session, and an Authorization header — even an empty one
      // — stops the backend from falling back to that session, which is exactly
      // how every reference image ended up as a blank box.
      credentials: 'same-origin',
      headers: authorization ? { [Authorization]: authorization } : undefined,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`);
        }
        return response.blob();
      })
      .then((blob) => {
        item.objectUrl = URL.createObjectURL(blob);
        return item.objectUrl;
      })
      .catch((error) => {
        // The previous version swallowed this, so a rejected image request was
        // indistinguishable from an image that had not loaded yet.
        console.warn(`[image] failed to load ${url}: ${error}`);
        imageCache.delete(cacheKey);
        throw error;
      });
  }

  return {
    promise: item.promise,
    release: () => {
      item.count -= 1;
      if (item.count <= 0) {
        item.timer = setTimeout(() => {
          if (item.count <= 0) {
            if (item.objectUrl) {
              URL.revokeObjectURL(item.objectUrl);
            }
            imageCache.delete(cacheKey);
          }
        }, 30000);
      }
    },
  };
};

// Check if a URL requires authentication (internal API URLs)
// Only attach Authorization headers to same-origin requests to prevent token leakage
const isAuthRequiredUrl = (url: string): boolean => {
  try {
    const parsedUrl = new URL(url, window.location.origin);
    if (parsedUrl.origin !== window.location.origin) {
      return false;
    }
    return (
      parsedUrl.pathname.startsWith('/api/v1/') ||
      parsedUrl.pathname.includes('/documents/images/')
    );
  } catch {
    return false;
  }
};

export type DocumentImageState = {
  src: string;
  failed: boolean;
  retry: () => void;
};

/**
 * Resolves a document image to a displayable URL and reports whether the
 * request failed, so a caller can say so instead of rendering an empty frame.
 */
export const useDocumentImage = (
  id: string,
  t?: string | number,
): DocumentImageState => {
  const directUrl = useMemo(() => buildDocumentImageUrl(id, t), [id, t]);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ src: string; failed: boolean }>({
    src: '',
    failed: false,
  });

  useEffect(() => {
    // For non-API URLs (e.g., base64, external URLs), use directly
    if (!isAuthRequiredUrl(directUrl)) {
      setState({ src: directUrl, failed: false });
      return;
    }

    // For API URLs that require authentication, always fetch with auth headers
    const authorization = getAuthorization();
    let ignore = false;
    setState({ src: '', failed: false });
    const { promise, release } = fetchDocumentImage(directUrl, authorization);
    promise
      .then((url) => {
        if (ignore) {
          return;
        }
        setState({ src: url, failed: false });
      })
      .catch(() => {
        if (!ignore) {
          setState({ src: '', failed: true });
        }
      });

    return () => {
      ignore = true;
      release();
    };
  }, [directUrl, attempt]);

  return {
    ...state,
    retry: () => setAttempt((previous) => previous + 1),
  };
};

export const useDocumentImageUrl = (id: string, t?: string | number) => {
  return useDocumentImage(id, t).src;
};

/**
 * Hook to convert any authenticated URL to a blob URL for use in <img> tags.
 * Use this for thumbnail URLs or any other API URLs that require authentication.
 */
export const useAuthenticatedImageUrl = (url: string | undefined | null) => {
  const [imageUrl, setImageUrl] = useState<string>('');

  useEffect(() => {
    if (!url || !isAuthRequiredUrl(url)) {
      setImageUrl(url || '');
      return;
    }

    const authorization = getAuthorization();
    let cancelled = false;
    setImageUrl('');

    const { promise, release } = fetchDocumentImage(url, authorization);
    promise
      .then((blobUrl) => {
        if (!cancelled) {
          setImageUrl(blobUrl);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setImageUrl('');
        }
      });

    return () => {
      cancelled = true;
      release();
    };
  }, [url]);

  return imageUrl;
};

/**
 * Component that renders an <img> tag with proper authentication for API URLs.
 * Use this instead of <img src={apiUrl}> when the URL requires authentication.
 */
export const AuthenticatedImg = ({
  src,
  alt,
  className,
  fallback,
  ...props
}: React.ImgHTMLAttributes<HTMLImageElement> & {
  fallback?: React.ReactNode;
}) => {
  const authenticatedSrc = useAuthenticatedImageUrl(src);

  if (!authenticatedSrc) return fallback ?? null;

  return (
    <img src={authenticatedSrc} alt={alt} className={className} {...props} />
  );
};

const Image = React.forwardRef<HTMLImageElement, IImage>(function Image(
  { id, t, label, className, ...props },
  ref,
) {
  const { t: translate } = useTranslation();
  const { src, failed, retry } = useDocumentImage(id, t);

  const labelBadge = label ? (
    <div className="absolute bottom-2 right-2 bg-accent-primary text-white px-2 py-0.5 rounded-xl text-xs font-normal backdrop-blur-sm">
      {label}
    </div>
  ) : null;

  // A failed request used to render an <img> with no src: an empty frame that
  // gave the reader no idea whether the picture was missing or still loading.
  if (failed) {
    return (
      <div
        className={classNames('relative inline-block w-full', className)}
        data-testid="image-load-failed"
      >
        <div className="flex h-40 w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-button bg-bg-card text-xs text-text-secondary">
          <ImageOff className="size-5" />
          <span>{translate('common.imageLoadFailed', 'Failed to load image')}</span>
          <Button variant="outline" size="sm" onClick={retry}>
            {translate('common.refresh', 'Refresh')}
          </Button>
        </div>
        {labelBadge}
      </div>
    );
  }

  const imageElement = (
    <img
      {...props}
      ref={ref}
      src={src || undefined}
      className={classNames('max-w-[45vw] max-h-[40wh] block', className)}
    />
  );

  if (!label) {
    return imageElement;
  }

  return (
    <div className="relative inline-block w-full">
      {imageElement}
      {labelBadge}
    </div>
  );
});

export default Image;

export const ImageWithPopover = ({ id }: { id: string }) => {
  return (
    <Popover>
      <PopoverTrigger>
        <Image id={id} className="max-h-[100px] inline-block"></Image>
      </PopoverTrigger>
      <PopoverContent>
        <Image id={id} className="max-w-[100px] object-contain"></Image>
      </PopoverContent>
    </Popover>
  );
};
