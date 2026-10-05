'use client';

import { MetadataFilter } from '@/components/metadata-filter';
import { RerankFormFields } from '@/components/rerank';
import { RerankCandidatesCountFormField } from '@/components/rerank-candidates-count-item';
import { SimilaritySliderFormField } from '@/components/similarity-slider';
import { TopNFormField } from '@/components/top-n-item';
import { prefixName } from '@/utils/form';

type RetrievalFieldsProps = { prefix?: string };

/**
 * The retrieval knobs: how similar a passage must be, how the vector and
 * full-text legs are weighted, how many candidates the reranker sees, how many
 * passages reach the model, and the metadata filter applied to both.
 */
export function RetrievalFields({ prefix = '' }: RetrievalFieldsProps) {
  return (
    <div className="space-y-6">
      <SimilaritySliderFormField
        isTooltipShown
        similarityName={prefixName(prefix, 'similarity_threshold')}
        similarityWeightName={prefixName(prefix, 'vector_similarity_weight')}
      ></SimilaritySliderFormField>

      <TopNFormField
        name={prefixName(prefix, 'top_n')}
      ></TopNFormField>

      <RerankCandidatesCountFormField
        name={prefixName(prefix, 'rerank_candidates_count')}
      ></RerankCandidatesCountFormField>

      <RerankFormFields prefix={prefix}></RerankFormFields>

      <MetadataFilter></MetadataFilter>
    </div>
  );
}
