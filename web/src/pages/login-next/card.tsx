import React, { createContext, useEffect, useState } from 'react';
import './index.less';

export const FlipFaceContext = createContext<'front' | 'back'>('front');

type IProps = {
  children: React.ReactNode;
  isLoginPage: boolean;
};
const FlipCard3D = (props: IProps) => {
  const { children, isLoginPage } = props;
  const [isFlipped, setIsFlipped] = useState(false);
  useEffect(() => {
    if (isLoginPage) {
      setIsFlipped(false);
    } else {
      setIsFlipped(true);
    }
  }, [isLoginPage]);
  const isBackfaceVisibilitySupported = () => {
    return (
      CSS.supports('backface-visibility', 'hidden') ||
      CSS.supports('-webkit-backface-visibility', 'hidden') ||
      CSS.supports('-moz-backface-visibility', 'hidden') ||
      CSS.supports('-ms-backface-visibility', 'hidden')
    );
  };
  return (
    <>
      {isBackfaceVisibilitySupported() && (
        // Both faces live in the same grid cell, so the card takes the height of
        // whichever face is taller instead of a reserved fixed height.
        <div className="perspective-1000 relative w-full">
          <div
            className={`transform-style-3d relative grid w-full ${isFlipped ? 'rotate-y-180' : ''}`}
          >
            {/* Front Face */}
            <div
              className="backface-hidden rotate-y-0 flex items-center justify-center [grid-area:1/1]"
              {...(!isFlipped ? { 'data-testid': 'auth-card-active' } : {})}
            >
              <FlipFaceContext.Provider value="front">
                {children}
              </FlipFaceContext.Provider>
            </div>

            {/* Back Face */}
            <div
              className="backface-hidden rotate-y-180 flex items-center justify-center [grid-area:1/1]"
              {...(isFlipped ? { 'data-testid': 'auth-card-active' } : {})}
            >
              <FlipFaceContext.Provider value="back">
                {children}
              </FlipFaceContext.Provider>
            </div>
          </div>
        </div>
      )}
      {!isBackfaceVisibilitySupported() && (
        <div data-testid="auth-card-active">
          <FlipFaceContext.Provider value={isFlipped ? 'back' : 'front'}>
            {children}
          </FlipFaceContext.Provider>
        </div>
      )}
    </>
  );
};

export default FlipCard3D;
