# Existing FastAPI service — endpoint inventory

- Generated: 2026-07-31T13:54:10
- Source: `https://bdsa-market-api-v1.onrender.com/openapi.json`
- Title: BDSA Market Intelligence API  ·  version 1.0.0
- Description: Read-only query API over the BDSA cannabis retail-scan dataset.

## Endpoints (6 operations)

### `POST /facets`

Facets

**Parameters**

| name | in | type | required | default | description |
| --- | --- | --- | --- | --- | --- |
| `x-api-key` | header | string |  |  |  |

**Request body**

**`FacetsRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `fields` | array<string> | yes |
| `limit` | integer |  |

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 | object | Successful Response |
| 422 | HTTPValidationError | Validation Error |

### `GET /health`

Health

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 |  | Successful Response |

### `GET /meta`

Meta

**Parameters**

| name | in | type | required | default | description |
| --- | --- | --- | --- | --- | --- |
| `x-api-key` | header | string |  |  |  |

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 | object | Successful Response |
| 422 | HTTPValidationError | Validation Error |

### `POST /search`

Search

**Parameters**

| name | in | type | required | default | description |
| --- | --- | --- | --- | --- | --- |
| `x-api-key` | header | string |  |  |  |

**Request body**

**`SearchRequest`**

| field | type | required |
| --- | --- | --- |
| `query` | string | yes |
| `field` | string |  |
| `partial` | boolean |  |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `limit` | integer |  |

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 | object | Successful Response |
| 422 | HTTPValidationError | Validation Error |

### `POST /timeseries`

Timeseries

**Parameters**

| name | in | type | required | default | description |
| --- | --- | --- | --- | --- | --- |
| `x-api-key` | header | string |  |  |  |

**Request body**

**`TimeseriesRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `metric` | string | yes |
| `series_dimension` | string |  |
| `series_limit` | integer |  |

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 | object | Successful Response |
| 422 | HTTPValidationError | Validation Error |

### `POST /top`

Top

**Parameters**

| name | in | type | required | default | description |
| --- | --- | --- | --- | --- | --- |
| `x-api-key` | header | string |  |  |  |

**Request body**

**`TopRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `dimension` | string | yes |
| `metric` | string | yes |
| `limit` | integer |  |
| `descending` | boolean |  |

**Responses**

| status | type | description |
| --- | --- | --- |
| 200 | object | Successful Response |
| 422 | HTTPValidationError | Validation Error |

## Component schemas

**`FacetsRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `fields` | array<string> | yes |
| `limit` | integer |  |

**`Filter`**

| field | type | required |
| --- | --- | --- |
| `field` | string | yes |
| `eq` | any |  |
| `in` | array<any> |  |
| `gte` | number |  |
| `lte` | number |  |

**`HTTPValidationError`**

| field | type | required |
| --- | --- | --- |
| `detail` | array<ValidationError> |  |

**`SearchRequest`**

| field | type | required |
| --- | --- | --- |
| `query` | string | yes |
| `field` | string |  |
| `partial` | boolean |  |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `limit` | integer |  |

**`TimeseriesRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `metric` | string | yes |
| `series_dimension` | string |  |
| `series_limit` | integer |  |

**`TopRequest`**

| field | type | required |
| --- | --- | --- |
| `period_grain` | string |  |
| `filters` | array<Filter> |  |
| `include_suppressed` | boolean |  |
| `dimension` | string | yes |
| `metric` | string | yes |
| `limit` | integer |  |
| `descending` | boolean |  |

**`ValidationError`**

| field | type | required |
| --- | --- | --- |
| `loc` | array<string | integer> | yes |
| `msg` | string | yes |
| `type` | string | yes |

