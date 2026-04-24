import { memo } from 'react';
import { getIngredientRiskMeta } from '@/lib/foodguard';
import type { IngredientAnalysisItem } from '@/types/report';

interface IngredientListProps {
  ingredients: IngredientAnalysisItem[];
  ingredientsText: string;
}

interface DisplayIngredientItem extends IngredientAnalysisItem {
  displayName: string;
}

const TRIGGER_PATTERNS = [
  /配\s*料\s*表\s*[：:]?\s*/u,
  /配\s*料\s*(?:[：:]|\s{1,})+\s*/u,
  /原\s*辅\s*料\s*[：:]?\s*/u,
  /主\s*要\s*原\s*料\s*[：:]?\s*/u,
  /原\s*料\s*(?:[：:]|\s{1,})+\s*/u,
];

const STOP_PATTERNS = [
  /净含量/u,
  /产品类别/u,
  /温馨提示/u,
  /食用方法/u,
  /饮用方法/u,
  /开袋后/u,
  /食用限量/u,
  /建议每天/u,
  /不适宜人群/u,
  /致敏物质/u,
  /致敏源/u,
  /贮存条件/u,
  /储存条件/u,
  /储藏方法/u,
  /保存方法/u,
  /请置于/u,
  /避免阳光/u,
  /喝前请摇匀/u,
  /请摇匀/u,
  /有沉淀/u,
  /颜色变化/u,
  /生产日期/u,
  /保质期/u,
  /执行标准/u,
];

const NOTICE_MARKERS = [
  '产品类别',
  '温馨提示',
  '食用方法',
  '饮用方法',
  '开袋后',
  '食用限量',
  '建议每天',
  '不适宜人群',
  '致敏原',
  '贮存条件',
  '储存条件',
  '储藏方法',
  '保存方法',
  '请置于',
  '避免阳光',
  '喝前请摇匀',
  '请摇匀',
  '有沉淀',
  '颜色变化',
  '净含量',
  '生产日期',
  '保质期',
  '执行标准',
];

const DOSAGE_PATTERN =
  /(?:\\(?:leqslant|geqslant)\s*)?(?:[<<=≥>]\s*)?\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|毫升|克|千克|天|日|袋|份|支|片|粒|包|%)+(?:\s*\/\s*[天日袋份次包])?/giu;
const AMOUNT_QUALIFIER_PATTERN = /(?:添加量|含量)\s*[≥≤<>]\s*\d/u;

export const IngredientList = memo(
  function IngredientList({ ingredients, ingredientsText }: IngredientListProps) {
    const displayedIngredients = buildDisplayedIngredients(ingredients, ingredientsText);
    const dangerCount = displayedIngredients.filter((item) => item.risk === 'danger').length;
    const warningCount = displayedIngredients.filter((item) => item.risk === 'warning').length;
    const safeCount = displayedIngredients.filter((item) => item.risk === 'safe').length;

    return (
      <div className="space-y-6">
        <div className="rounded-xl bg-slate-50 p-5">
          <h4 className="mb-4 text-sm font-semibold text-slate-900">配料风险分布</h4>
          <RiskBar
            label="高风险"
            count={dangerCount}
            total={displayedIngredients.length}
            colorClass="bg-rose-500"
          />
          <RiskBar
            label="中风险"
            count={warningCount}
            total={displayedIngredients.length}
            colorClass="bg-amber-500"
          />
          <RiskBar
            label="安全"
            count={safeCount}
            total={displayedIngredients.length}
            colorClass="bg-emerald-500"
          />
        </div>

        <div className="rounded-xl bg-white p-5">
          <h4 className="mb-4 text-sm font-semibold text-slate-900">识别到的原始配料信息</h4>
          <p className="whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm leading-7 text-slate-600">
            {ingredientsText || '未识别到原始配料文本'}
          </p>
        </div>

        <div>
          <h4 className="mb-4 text-sm font-semibold text-slate-900">配料说明</h4>
          {displayedIngredients.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
              {displayedIngredients.map((item) => {
                const riskMeta = getIngredientRiskMeta(item.risk);
                return (
                  <div
                    key={`${item.displayName}-${item.risk}`}
                    className={`rounded-xl border p-4 ${riskMeta.cardClass}`}
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${riskMeta.chipClass}`}>
                        {riskMeta.label}
                      </span>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-slate-900">{item.displayName}</span>
                        <span className={`h-2.5 w-2.5 rounded-full ${riskMeta.dotClass}`} />
                      </div>
                      <p className="text-xs leading-5 text-slate-600">{item.description}</p>
                      {item.function_category && (
                        <div className="text-xs text-slate-500">
                          功能类别：{item.function_category}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-sm text-slate-400">
              暂无结构化配料风险结果
            </div>
          )}
        </div>
      </div>
    );
  },
  (prevProps, nextProps) =>
    prevProps.ingredients === nextProps.ingredients &&
    prevProps.ingredientsText === nextProps.ingredientsText,
);

function buildDisplayedIngredients(
  ingredients: IngredientAnalysisItem[],
  ingredientsText: string,
): DisplayIngredientItem[] {
  const keywordMatched = matchIngredientsToKeywords(ingredients, extractIngredientKeywords(ingredientsText));
  if (keywordMatched.length > 0) {
    return keywordMatched;
  }
  return buildFallbackIngredients(ingredients);
}

function extractIngredientKeywords(ingredientsText: string): string[] {
  const normalizedText = normalizeSourceText(ingredientsText);
  if (!normalizedText) {
    return [];
  }

  const text = locateIngredientText(normalizedText);
  const seen = new Set<string>();
  const keywords: string[] = [];

  for (const segment of text.split(/[、，,；;\n]+/u)) {
    const keyword = toIngredientTitle(segment);
    if (!isLikelyIngredientKeyword(keyword) || seen.has(keyword)) {
      continue;
    }
    seen.add(keyword);
    keywords.push(keyword);
  }

  return mergeFragmentedIngredientKeywords(keywords);
}

function mergeFragmentedIngredientKeywords(keywords: string[]): string[] {
  const merged: string[] = [];
  let index = 0;

  while (index < keywords.length) {
    const current = keywords[index];
    const next = keywords[index + 1];

    if (current === '单' && next?.startsWith('双')) {
      merged.push(`${current}、${next}`);
      index += 2;
      continue;
    }

    merged.push(current);
    index += 1;
  }

  return merged;
}

function buildFallbackIngredients(ingredients: IngredientAnalysisItem[]): DisplayIngredientItem[] {
  const seen = new Set<string>();
  const fallbackItems: DisplayIngredientItem[] = [];

  for (const item of ingredients) {
    const displayName = toIngredientTitle(item.name);
    if (!isLikelyIngredientKeyword(displayName) || seen.has(displayName)) {
      continue;
    }
    seen.add(displayName);
    fallbackItems.push({ ...item, displayName });
  }

  return fallbackItems;
}

function matchIngredientsToKeywords(
  ingredients: IngredientAnalysisItem[],
  keywords: string[],
): DisplayIngredientItem[] {
  const usedIndexes = new Set<number>();
  const matchedItems: DisplayIngredientItem[] = [];

  for (const keyword of keywords) {
    let bestMatchIndex = -1;
    let bestMatchScore = 0;

    for (const [index, item] of ingredients.entries()) {
      if (usedIndexes.has(index)) {
        continue;
      }

      const score = getKeywordMatchScore(keyword, item.name);
      if (score > bestMatchScore) {
        bestMatchScore = score;
        bestMatchIndex = index;
      }
    }

    if (bestMatchIndex === -1) {
      continue;
    }

    usedIndexes.add(bestMatchIndex);
    matchedItems.push({
      ...ingredients[bestMatchIndex],
      displayName: keyword,
    });
  }

  return matchedItems;
}

function normalizeSourceText(value: string): string {
  return value
    .replace(/\u3000/g, ' ')
    .replace(/\r/g, '')
    .replace(/[ \t\f\v]+/g, ' ')
    .trim();
}

function locateIngredientText(value: string): string {
  const triggerMatch = findFirstMatch(value, TRIGGER_PATTERNS);
  const startIndex = triggerMatch ? triggerMatch.index + triggerMatch.text.length : 0;
  const candidate = value.slice(startIndex).replace(/^[:：\s]+/u, '');
  const stopIndex = findFirstStopIndex(candidate);

  if (stopIndex === -1) {
    return candidate;
  }

  return candidate.slice(0, stopIndex).trim();
}

function findFirstMatch(
  value: string,
  patterns: RegExp[],
): { index: number; text: string } | null {
  const matches = patterns
    .map((pattern) => {
      const match = pattern.exec(value);
      if (!match || match.index === undefined) {
        return null;
      }
      return {
        index: match.index,
        text: match[0],
      };
    })
    .filter((match): match is { index: number; text: string } => match !== null)
    .sort((a, b) => a.index - b.index || b.text.length - a.text.length);

  return matches[0] ?? null;
}

function findFirstStopIndex(value: string): number {
  return STOP_PATTERNS.reduce((firstIndex, pattern) => {
    const match = pattern.exec(value);
    if (!match || match.index < 0) {
      return firstIndex;
    }
    if (firstIndex === -1 || match.index < firstIndex) {
      return match.index;
    }
    return firstIndex;
  }, -1);
}

function toIngredientTitle(value: string): string {
  let cleaned = value
    .replace(/\$/g, ' ')
    .replace(/\\geqslant/gu, '≥')
    .replace(/\\leqslant/gu, '≤')
    .replace(/≧/gu, '≥')
    .replace(/≦/gu, '≤')
    .replace(/>\s*=/gu, '≥')
    .replace(/<\s*=/gu, '≤')
    .replace(/\s*([≥≤<>])\s*/gu, '$1')
    .replace(/^(?:配料表|配料|原辅料|主要原料|原料|成分)[:：\s]*/u, '')
    .trim();

  const markerIndex = NOTICE_MARKERS.reduce((firstIndex, marker) => {
    const currentIndex = cleaned.indexOf(marker);
    if (currentIndex === -1) {
      return firstIndex;
    }
    if (firstIndex === -1 || currentIndex < firstIndex) {
      return currentIndex;
    }
    return firstIndex;
  }, -1);

  if (markerIndex > 0) {
    cleaned = cleaned.slice(0, markerIndex);
  }

  const shouldKeepAmountQualifier = AMOUNT_QUALIFIER_PATTERN.test(cleaned);

  return (shouldKeepAmountQualifier ? cleaned : cleaned.replace(DOSAGE_PATTERN, ' '))
    .replace(/[。]+$/u, '')
    .replace(/^[\s:：;；，,。、]+|[\s:：;；，,。、]+$/gu, '')
    .trim();
}

function isLikelyIngredientKeyword(value: string): boolean {
  if (!value) {
    return false;
  }

  if (/[。！？]/u.test(value)) {
    return false;
  }

  if (value.length > 30) {
    return false;
  }

  return !NOTICE_MARKERS.some((marker) => value.includes(marker));
}

function getKeywordMatchScore(keyword: string, itemName: string): number {
  const normalizedKeyword = normalizeIngredientKey(keyword);
  const normalizedItemName = normalizeIngredientKey(itemName);

  if (!normalizedKeyword || !normalizedItemName) {
    return 0;
  }

  if (
    normalizedItemName.includes(normalizedKeyword) ||
    normalizedKeyword.includes(normalizedItemName)
  ) {
    return Math.min(normalizedKeyword.length, normalizedItemName.length) + 100;
  }

  const overlapLength = longestCommonSubstringLength(normalizedKeyword, normalizedItemName);
  const minLength = Math.min(normalizedKeyword.length, normalizedItemName.length);

  if (minLength === 0) {
    return 0;
  }

  const overlapRatio = overlapLength / minLength;
  if (overlapLength >= 4 && overlapRatio >= 0.7) {
    return overlapLength;
  }

  return 0;
}

function normalizeIngredientKey(value: string): string {
  return toIngredientTitle(value)
    .replace(/[()（）【】[\]{}]/g, '')
    .replace(/[^0-9A-Za-z\u4e00-\u9fff]/gu, '');
}

function longestCommonSubstringLength(left: string, right: string): number {
  const row = new Array(right.length + 1).fill(0);
  let maxLength = 0;

  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    for (let rightIndex = right.length; rightIndex >= 1; rightIndex -= 1) {
      if (left[leftIndex - 1] === right[rightIndex - 1]) {
        row[rightIndex] = row[rightIndex - 1] + 1;
        if (row[rightIndex] > maxLength) {
          maxLength = row[rightIndex];
        }
      } else {
        row[rightIndex] = 0;
      }
    }
  }

  return maxLength;
}

function RiskBar({
  label,
  count,
  total,
  colorClass,
}: {
  label: string;
  count: number;
  total: number;
  colorClass: string;
}) {
  const percentage = total > 0 ? (count / total) * 100 : 0;

  return (
    <div className="mb-3 flex items-center gap-4 last:mb-0">
      <div className="flex w-20 items-center gap-1 text-xs text-slate-600">
        <div className={`h-2 w-2 rounded-full ${colorClass}`} />
        {label}
      </div>
      <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${percentage}%` }} />
      </div>
      <div className="w-12 text-right text-xs text-slate-600">{count}项</div>
    </div>
  );
}
