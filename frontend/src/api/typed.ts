/** Types for calling the API by its OpenAPI paths (``schema.d.ts``, made by ``npm run
 * gen:api``): a path's parameters, its query, its JSON body and its 200 answer. The
 * calls themselves are ``apiGet`` and ``apiPost`` in ``client.ts``, over its
 * ``request()`` (same headers, AbortSignal and NetworkError). ``buildUrl`` fills a path
 * template like ``/api/maintenance/jobs/{job_id}`` and appends the query. */
import type { paths } from "./schema";

export type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

/** The paths that answer ``M``. */
export type PathOf<M extends HttpMethod> = {
  [P in keyof paths]: [NonNullable<paths[P][M]>] extends [never] ? never : P;
}[keyof paths];

/** The OpenAPI operation of ``M`` on ``P``. */
export type Operation<P extends keyof paths, M extends HttpMethod> = NonNullable<paths[P][M]>;

type Json<R> = R extends { content: { "application/json": infer B } } ? B : void;

/** What a successful call answers (its 200 JSON); ``void`` for a 204. */
export type ResponseOf<O> = O extends { responses: { 200: infer R } }
  ? Json<R>
  : O extends { responses: { 204: unknown } }
    ? void
    : unknown;

/** The path parameters (``never``: the path has none). */
export type PathParamsOf<O> = O extends { parameters: { path: infer P } } ? P : never;

/** The query parameters (``never``: none). */
export type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

/** The JSON body: ``never`` when there is none, ``| undefined`` when it is optional. */
export type BodyOf<O> = O extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : O extends { requestBody?: never }
    ? never
    : O extends { requestBody?: { content: { "application/json": infer B } } }
      ? B | undefined
      : never;

type PathPart<O> = [PathParamsOf<O>] extends [never] ? { path?: undefined } : { path: PathParamsOf<O> };
type QueryPart<O> = [QueryOf<O>] extends [never] ? { query?: undefined } : { query?: QueryOf<O> };
type BodyPart<O> = [BodyOf<O>] extends [never]
  ? { body?: undefined }
  : undefined extends BodyOf<O>
    ? { body?: BodyOf<O> }
    : { body: BodyOf<O> };

/** What a call of ``O`` takes besides its path; ``body`` only where ``M`` sends one. */
export type CallOptions<O, M extends HttpMethod> = PathPart<O> &
  QueryPart<O> &
  (M extends "get" | "delete" ? unknown : BodyPart<O>) & { signal?: AbortSignal };

/** The options argument, which may be left out when nothing in it is required. */
export type CallArgs<O, M extends HttpMethod> =
  Record<string, never> extends CallOptions<O, M> ? [options?: CallOptions<O, M>] : [options: CallOptions<O, M>];

type QueryValue = string | number | boolean | null | undefined;

/** ``template`` with each ``{name}`` replaced by its encoded value, then the query (keys in
 * order; null and undefined left out; an array gives the key once per value). */
export function buildUrl(
  template: string,
  path?: Record<string, string | number>,
  query?: Record<string, QueryValue | readonly QueryValue[]>,
): string {
  const url = template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = path?.[name];
    if (value === undefined) throw new Error(`${template}: no value for {${name}}`);
    return encodeURIComponent(String(value));
  });
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    for (const v of Array.isArray(value) ? value : [value]) {
      if (v !== null && v !== undefined) search.append(key, String(v));
    }
  }
  const qs = search.toString();
  return qs ? `${url}?${qs}` : url;
}
