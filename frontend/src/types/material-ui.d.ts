// Type declarations for Material UI and other modules

// Material UI Components
declare module '@mui/material' {
  import * as React from 'react';
  export interface ButtonProps {
    variant?: 'text' | 'outlined' | 'contained';
    color?: 'inherit' | 'primary' | 'secondary' | 'success' | 'error' | 'info' | 'warning';
    size?: 'small' | 'medium' | 'large';
    startIcon?: React.ReactNode;
    endIcon?: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    sx?: any;
    children?: React.ReactNode;
    component?: any; // Added for router integration
    to?: string; // Added for router integration
    fullWidth?: boolean; // Added for full width buttons
    type?: 'button' | 'submit' | 'reset'; // Added for form buttons
  }
  export const Button: React.FC<ButtonProps>;
  
  // Add other component interfaces as needed
  export const Box: React.FC<any>;
  export const Paper: React.FC<any>;
  export const Typography: React.FC<any>;
  export const Grid: React.FC<any>;
  export const Card: React.FC<any>;
  export const CardContent: React.FC<any>;
  export const CardActions: React.FC<any>;
  export const Table: React.FC<any>;
  export const TableBody: React.FC<any>;
  export const TableCell: React.FC<any>;
  export const TableContainer: React.FC<any>;
  export const TableHead: React.FC<any>;
  export const TableRow: React.FC<any>;
  export const TablePagination: React.FC<any>; // Added TablePagination
  export const Chip: React.FC<any>;
  export const TextField: React.FC<any>;
  export const InputAdornment: React.FC<any>;
  export const IconButton: React.FC<any>;
  export const Badge: React.FC<any>;
  export const Divider: React.FC<any>;
  export const LinearProgress: React.FC<any>;
  export const Tab: React.FC<any>;
  export const Tabs: React.FC<any>;
  export const Dialog: React.FC<any>;
  export const DialogActions: React.FC<any>;
  export const DialogContent: React.FC<any>;
  export const DialogTitle: React.FC<any>;
  export const FormControl: React.FC<any>;
  export const InputLabel: React.FC<any>;
  export const Select: React.FC<any>;
  export const MenuItem: React.FC<any>;
  export const Switch: React.FC<any>;
  export const Tooltip: React.FC<any>;
  export const Alert: React.FC<any>;
  export const CircularProgress: React.FC<any>;
  export const List: React.FC<any>;
  export const ListItem: React.FC<any>;
  export const ListItemText: React.FC<any>;
  export const ListItemAvatar: React.FC<any>;
  export const ListItemSecondaryAction: React.FC<any>;
  export const ListItemButton: React.FC<any>; // Added ListItemButton
  export const Avatar: React.FC<any>;
  export const Autocomplete: React.FC<any>;
  export const Checkbox: React.FC<any>;
  
  export interface SelectChangeEvent<T = unknown> {
    target: {
      value: T;
      name: string;
    };
  }
}

// Material UI Icons
declare module '@mui/icons-material' {
  import * as React from 'react';
  
  interface IconProps {
    color?: 'inherit' | 'primary' | 'secondary' | 'action' | 'disabled' | 'error' | 'success' | 'warning' | 'info';
    fontSize?: 'small' | 'medium' | 'large' | 'inherit';
    sx?: any;
  }
  
  export const Search: React.FC<IconProps>;
  export const FilterList: React.FC<IconProps>;
  export const Add: React.FC<IconProps>;
  export const Edit: React.FC<IconProps>;
  export const Lock: React.FC<IconProps>;
  export const Close: React.FC<IconProps>;
  export const Delete: React.FC<IconProps>;
  export const Person: React.FC<IconProps>;
  export const FindInPage: React.FC<IconProps>;
  export const LocalOffer: React.FC<IconProps>;
  export const Refresh: React.FC<IconProps>;
  export const Alarm: React.FC<IconProps>;
  export const AssignmentTurnedIn: React.FC<IconProps>;
  export const AssignmentLate: React.FC<IconProps>;
  export const Folder: React.FC<IconProps>;
  export const FolderOpen: React.FC<IconProps>;
  export const BarChart: React.FC<IconProps>;
  export const Description: React.FC<IconProps>;
}

// React
declare module 'react' {
  namespace React {
    // Type definitions for React components
    interface Element {}
    
    interface ReactElement<P = any, T extends string | JSXElementConstructor<any> = string | JSXElementConstructor<any>> {
      type: T;
      props: P;
      key: Key | null;
    }
    
    type Key = string | number;
    
    type JSXElementConstructor<P> = (props: P) => ReactElement<any, any> | null;
    
    interface FC<P = {}> {
      (props: P & { children?: ReactNode }): ReactElement<any, any> | null;
      displayName?: string;
    }
    
    type ReactText = string | number;
    type ReactChild = ReactElement | ReactText;
    
    interface ReactNodeArray extends Array<ReactNode> {}
    type ReactFragment = {} | ReactNodeArray;
    type ReactNode = ReactChild | ReactFragment | ReactPortal | boolean | null | undefined;
    
    interface ReactPortal extends ReactElement {
      key: Key | null;
      children: ReactNode;
    }
    
    // Events
    interface SyntheticEvent<T = Element, E = Event> extends BaseSyntheticEvent<E, EventTarget & T, EventTarget> {}
    
    interface BaseSyntheticEvent<E = object, C = any, T = any> {
      nativeEvent: E;
      currentTarget: C;
      target: T;
      bubbles: boolean;
      cancelable: boolean;
      defaultPrevented: boolean;
      eventPhase: number;
      isTrusted: boolean;
      preventDefault(): void;
      isDefaultPrevented(): boolean;
      stopPropagation(): void;
      isPropagationStopped(): boolean;
      persist(): void;
      timeStamp: number;
      type: string;
    }
    
    interface ChangeEvent<T = Element> extends SyntheticEvent<T> {
      target: EventTarget & T;
    }
    
    interface FormEvent<T = Element> extends SyntheticEvent<T> {}
    
    interface MouseEvent<T = Element, E = NativeMouseEvent> extends SyntheticEvent<T, E> {
      altKey: boolean;
      button: number;
      buttons: number;
      clientX: number;
      clientY: number;
      ctrlKey: boolean;
      metaKey: boolean;
      movementX: number;
      movementY: number;
      pageX: number;
      pageY: number;
      relatedTarget: EventTarget | null;
      screenX: number;
      screenY: number;
      shiftKey: boolean;
    }
    
    // Adding StrictMode
    const StrictMode: React.FC<{ children?: ReactNode }>;
    
    // Adding Component class
    class Component<P = {}, S = {}> {
      constructor(props: P);
      props: P;
      state: S;
      setState(state: S | ((prevState: S, props: P) => S), callback?: () => void): void;
      forceUpdate(callback?: () => void): void;
      render(): ReactNode;
    }
  }
  
  export = React;
  export as namespace React;
  
  // React Hooks
  export function useState<T>(initialState: T | (() => T)): [T, React.Dispatch<React.SetStateAction<T>>];
  export function useEffect(effect: () => void | (() => void), deps?: readonly any[]): void;
  export function useContext<T>(context: React.Context<T>): T;
  export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: readonly any[]): T;
  export function useMemo<T>(factory: () => T, deps: readonly any[]): T;
  export function useRef<T>(initialValue: T): React.MutableRefObject<T>;
  export function useRef<T>(initialValue: T | null): React.RefObject<T>;
  export function useRef<T = undefined>(): React.MutableRefObject<T | undefined>;
  
  export interface Context<T> {
    Provider: Provider<T>;
    Consumer: Consumer<T>;
    displayName?: string;
  }
  
  export interface Provider<T> {
    (props: ProviderProps<T>): React.ReactElement | null;
  }
  
  export interface Consumer<T> {
    (props: ConsumerProps<T>): React.ReactElement | null;
  }
  
  export interface ProviderProps<T> {
    value: T;
    children?: React.ReactNode;
  }
  
  export interface ConsumerProps<T> {
    children: (value: T) => React.ReactNode;
  }
  
  export type Dispatch<A> = (value: A) => void;
  export type SetStateAction<S> = S | ((prevState: S) => S);
  export type MutableRefObject<T> = { current: T };
  export type RefObject<T> = { readonly current: T | null };
  
  export function createContext<T>(defaultValue: T): Context<T>;
  
  // Adding StrictMode to exported namespace as well
  export const StrictMode: React.FC<{ children?: React.ReactNode }>;
}

// React Router DOM
declare module 'react-router-dom' {
  import React from 'react';
  
  export interface RouteObject {
    path: string;
    element?: React.ReactNode;
    children?: RouteObject[];
    index?: boolean;
  }
  
  export interface NavigateOptions {
    replace?: boolean;
    state?: any;
    preventScrollReset?: boolean;
  }
  
  export function useNavigate(): (to: string, options?: NavigateOptions) => void;
  export function useParams(): Record<string, string>;
  export function useLocation(): Location;
  
  interface Location {
    pathname: string;
    search: string;
    hash: string;
    state: any;
    key: string;
  }
  
  export interface LinkProps {
    to: string;
    replace?: boolean;
    state?: any;
    preventScrollReset?: boolean;
    relative?: 'route' | 'path';
    children?: React.ReactNode;
    style?: React.CSSProperties;
    className?: string;
  }
  
  export const Link: React.FC<LinkProps>;
  
  export interface RoutesProps {
    children?: React.ReactNode;
    location?: Location;
  }
  
  export const Routes: React.FC<RoutesProps>;
  
  export interface RouteProps {
    path?: string;
    index?: boolean;
    children?: React.ReactNode;
    element?: React.ReactNode;
  }
  
  export const Route: React.FC<RouteProps>;
  
  // Adding BrowserRouter
  export interface BrowserRouterProps {
    basename?: string;
    children?: React.ReactNode;
    window?: Window;
  }
  
  export const BrowserRouter: React.FC<BrowserRouterProps>;
  
  // Adding Navigate
  export interface NavigateProps {
    to: string;
    replace?: boolean;
    state?: any;
  }
  
  export const Navigate: React.FC<NavigateProps>;
}

// Axios
declare module 'axios' {
  export interface AxiosRequestConfig {
    url?: string;
    method?: string;
    baseURL?: string;
    headers?: any;
    params?: any;
    data?: any;
    timeout?: number;
    withCredentials?: boolean;
    responseType?: 'arraybuffer' | 'blob' | 'document' | 'json' | 'text' | 'stream'; // Added responseType
  }
  
  export interface AxiosResponse<T = any> {
    data: T;
    status: number;
    statusText: string;
    headers: any;
    config: AxiosRequestConfig;
  }
  
  export interface AxiosError<T = any> extends Error {
    config: AxiosRequestConfig;
    code?: string;
    request?: any;
    response?: AxiosResponse<T>;
  }

  export interface AxiosInterceptorManager<V> {
    use(
      onFulfilled?: (value: V) => V | Promise<V>,
      onRejected?: (error: any) => any
    ): number;
    eject(id: number): void;
  }
  
  export interface AxiosInstance {
    (config: AxiosRequestConfig): Promise<AxiosResponse>;
    (url: string, config?: AxiosRequestConfig): Promise<AxiosResponse>;
    defaults: AxiosRequestConfig;
    interceptors: {
      request: AxiosInterceptorManager<AxiosRequestConfig>;
      response: AxiosInterceptorManager<AxiosResponse>;
    };
    get<T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>;
    post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>;
    put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>;
    delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>>;
    create(config?: AxiosRequestConfig): AxiosInstance; // Added create method
  }
  
  export function create(config?: AxiosRequestConfig): AxiosInstance;
  
  const axios: AxiosInstance;
  export default axios;
}

// JSX Runtime
declare module 'react/jsx-runtime' {
  import type React from 'react';
  
  export namespace JSX {
    interface Element extends React.ReactElement<any, any> {}
    
    interface ElementClass extends React.Component<any> {
      render(): React.ReactNode;
    }
    
    interface ElementAttributesProperty {
      props: {};
    }
    
    interface ElementChildrenAttribute {
      children: {};
    }
    
    type LibraryManagedAttributes<C, P> = C extends React.ComponentClass<infer CP>
      ? P & Omit<CP, keyof P>
      : P;
      
    interface IntrinsicAttributes {
      key?: React.Key;
    }
    
    interface IntrinsicClassAttributes<T> {
      ref?: React.LegacyRef<T>;
    }
    
    interface IntrinsicElements {
      // HTML
      a: any;
      abbr: any;
      address: any;
      area: any;
      article: any;
      aside: any;
      audio: any;
      b: any;
      base: any;
      bdi: any;
      bdo: any;
      big: any;
      blockquote: any;
      body: any;
      br: any;
      button: any;
      canvas: any;
      caption: any;
      cite: any;
      code: any;
      col: any;
      colgroup: any;
      data: any;
      datalist: any;
      dd: any;
      del: any;
      details: any;
      dfn: any;
      dialog: any;
      div: any;
      dl: any;
      dt: any;
      em: any;
      embed: any;
      fieldset: any;
      figcaption: any;
      figure: any;
      footer: any;
      form: any;
      h1: any;
      h2: any;
      h3: any;
      h4: any;
      h5: any;
      h6: any;
      head: any;
      header: any;
      hgroup: any;
      hr: any;
      html: any;
      i: any;
      iframe: any;
      img: any;
      input: any;
      ins: any;
      kbd: any;
      keygen: any;
      label: any;
      legend: any;
      li: any;
      link: any;
      main: any;
      map: any;
      mark: any;
      menu: any;
      menuitem: any;
      meta: any;
      meter: any;
      nav: any;
      noscript: any;
      object: any;
      ol: any;
      optgroup: any;
      option: any;
      output: any;
      p: any;
      param: any;
      picture: any;
      pre: any;
      progress: any;
      q: any;
      rp: any;
      rt: any;
      ruby: any;
      s: any;
      samp: any;
      script: any;
      section: any;
      select: any;
      small: any;
      source: any;
      span: any;
      strong: any;
      style: any;
      sub: any;
      summary: any;
      sup: any;
      table: any;
      tbody: any;
      td: any;
      textarea: any;
      tfoot: any;
      th: any;
      thead: any;
      time: any;
      title: any;
      tr: any;
      track: any;
      u: any;
      ul: any;
      var: any;
      video: any;
      wbr: any;
      // SVG
      svg: any;
      circle: any;
      clipPath: any;
      defs: any;
      ellipse: any;
      foreignObject: any;
      g: any;
      image: any;
      line: any;
      linearGradient: any;
      marker: any;
      mask: any;
      path: any;
      pattern: any;
      polygon: any;
      polyline: any;
      radialGradient: any;
      rect: any;
      stop: any;
      symbol: any;
      text: any;
      tspan: any;
      use: any;
    }
  }
  
  export function jsx(type: any, props: any, key?: string): JSX.Element;
  export function jsxs(type: any, props: any, key?: string): JSX.Element;
  export function Fragment(props: { children?: React.ReactNode }): JSX.Element;
}
