# AI Trading Terminal v1.0 — Simulação

Este protótipo consulta dados públicos de mercado e mantém uma carteira **fictícia**. Não envia ordens reais e não pede chaves privadas.

## Como publicar pelo celular Android (gratuito)

1. Extraia `ai_trading_terminal_v1.zip` no celular, se o aplicativo de arquivos permitir.
2. Entre em https://github.com e crie uma conta gratuita, caso ainda não tenha.
3. Crie um repositório novo, por exemplo `ai-trading-terminal`.
4. Envie os arquivos `app.py` e `requirements.txt` para a raiz do repositório.
5. Entre em https://share.streamlit.io/ e conecte sua conta GitHub.
6. Escolha o repositório, a branch principal e `app.py` como arquivo principal.
7. Clique em Deploy. A plataforma instalará as dependências e fornecerá um endereço para abrir o painel.

A disponibilidade, os limites e os termos das plataformas gratuitas podem mudar. Não coloque chaves, senhas ou dados pessoais em arquivos públicos.

## Como usar

- Abra o painel.
- Confira os preços de mercado carregados.
- Na barra lateral, toque em **Consultar mercado e simular**.
- Veja os sinais, carteira virtual, eventos e histórico.
- Use **Reiniciar simulação** para voltar ao saldo inicial.

## Limitações conhecidas

- A análise é acionada manualmente; não é um serviço de execução contínua 24/7.
- Analisa até 40 pares USDT de maior volume, não todos os tokens existentes.
- A simulação é mantida na sessão do Streamlit e pode ser perdida quando a sessão/app reinicia.
- Taxas de 0,10% por lado são uma hipótese ilustrativa, não uma cotação da corretora.
- Não simula completamente spread, slippage, liquidez, latência, falhas de execução ou todos os riscos de tokens.
- Indicadores EMA/RSI são demonstrações didáticas, não uma estratégia validada.
- Nenhuma ordem real é enviada. Não existe integração com endpoints privados de trading.

## Tecnologias

Python, Streamlit, pandas, requests e API pública de mercado da Binance.
