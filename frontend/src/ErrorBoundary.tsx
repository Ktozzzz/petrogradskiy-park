import React from "react";

type Props = { children: React.ReactNode };
type State = { error: Error | null };

/**
 * Ловит ошибки рендера (например, неожиданную структуру данных объекта)
 * и показывает понятное сообщение вместо белого экрана.
 */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Ошибка интерфейса:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="fatal">
          <div className="fatal-box">
            <h2>Что-то пошло не так 😔</h2>
            <p>
              Не удалось отобразить страницу:{" "}
              <code>{this.state.error.message || "неизвестная ошибка"}</code>
            </p>
            <p className="muted">
              Данные объекта могли прийти в неожиданном виде. Попробуйте открыть
              объект заново или перезагрузите страницу.
            </p>
            <div className="fatal-actions">
              <button onClick={() => this.setState({ error: null })}>
                Попробовать снова
              </button>
              <button onClick={() => window.location.reload()}>
                Перезагрузить страницу
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
