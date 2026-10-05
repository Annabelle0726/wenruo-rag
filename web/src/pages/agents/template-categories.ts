import { IFlowTemplate } from '@/interfaces/database/agent';

/**
 * Canvas categories a template advertises. `canvas_types` is the current field;
 * `canvas_type` is the legacy single-value form still shipped by older
 * templates, so both views have to be read the same way everywhere.
 */
export function getTemplateCanvasTypes(template: IFlowTemplate): string[] {
  if (Array.isArray(template.canvas_types) && template.canvas_types.length > 0) {
    return template.canvas_types.filter(
      (canvasType): canvasType is string => typeof canvasType === 'string',
    );
  }

  return template.canvas_type ? [template.canvas_type] : [];
}

export function templateMatchesCategory(
  template: IFlowTemplate,
  category: string,
): boolean {
  const target = category.toLowerCase();

  return getTemplateCanvasTypes(template).some(
    (canvasType) => canvasType.toLowerCase() === target,
  );
}

export function collectTemplateCategories(
  templates: IFlowTemplate[],
): string[] {
  const categories = new Set<string>();

  templates.forEach((template) => {
    getTemplateCanvasTypes(template).forEach((canvasType) =>
      categories.add(canvasType),
    );
  });

  return Array.from(categories);
}
