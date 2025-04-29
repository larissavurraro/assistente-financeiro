def processar_mensagem():
    msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    if not from_number:
        return Response("<Response><Message>❌ Número de origem não identificado.</Message></Response>", mimetype="application/xml")

    # Se for áudio, processa
    if media_url and media_type and ("audio" in media_type.lower() or "voice" in media_type.lower()):
        texto_transcrito = processar_audio(media_url)
        if texto_transcrito:
            msg = texto_transcrito.strip()

    msg = msg.lower().strip()

    # Verifica comandos
    if "resumo geral" in msg:
        return gerar_resumo_geral(from_number)
    if "resumo hoje" in msg:
        return gerar_resumo_hoje(from_number)
    if "resumo por categoria" in msg:
        return gerar_resumo_categoria(from_number)
    if "resumo mensal" in msg:
        return gerar_resumo_mensal(from_number)
    if "resumo da larissa" in msg:
        return gerar_resumo(from_number, "LARISSA", 30, "Resumo do Mês")
    if "resumo do thiago" in msg:
        return gerar_resumo(from_number, "THIAGO", 30, "Resumo do Mês")
    if "resumo do mês" in msg:
        return gerar_resumo(from_number, "TODOS", 30, "Resumo do Mês")
    if "resumo da semana" in msg:
        return gerar_resumo(from_number, "TODOS", 7, "Resumo da Semana")

    # Se não for comando de resumo, trata como despesa
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response(
            "<Response><Message>❌ Formato inválido. Envie: Nome, data, categoria, descrição, valor\n\nExemplo: Thiago, hoje, alimentação, mercado, 150,00</Message></Response>",
            mimetype="application/xml"
        )

    responsavel, data, categoria_input, descricao, valor = partes

    # Processa a data
    if data.lower() == "hoje":
        data_formatada = datetime.now().strftime("%d/%m/%Y")
    else:
        try:
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.now().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.now().strftime("%d/%m/%Y")

    # Define a categoria
    if categoria_input.strip() and categoria_input.upper() != "OUTROS":
        categoria = categoria_input.upper()
    else:
        categoria = classificar_categoria(descricao)

    # Processa descrição, responsável e valor
    descricao = descricao.upper()
    responsavel = responsavel.upper()

    try:
        valor_float = parse_valor(valor)
        valor_formatado = formatar_valor(valor_float)
    except:
        valor_formatado = valor

    # Corrige ordem dos dados
    nova_linha = [
        data_formatada,
        categoria.upper(),
        descricao.upper(),
        responsavel.upper(),
        valor_formatado
    ]

    # Salva na planilha
    sheet.append_row(nova_linha)

    resposta_texto = (
        f"✅ Despesa registrada com sucesso!\n\n"
        f"📅 Data: {data_formatada}\n"
        f"📂 Categoria: {categoria.upper()}\n"
        f"📝 Descrição: {descricao.upper()}\n"
        f"👤 Responsável: {responsavel.upper()}\n"
        f"💸 Valor: {valor_formatado}"
    )

    return enviar_mensagem_audio(from_number, resposta_texto)