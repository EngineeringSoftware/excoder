package org.throwgen.core;

import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.BooleanLiteralExpr;
import com.github.javaparser.ast.expr.CharLiteralExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.IntegerLiteralExpr;
import com.github.javaparser.ast.expr.NullLiteralExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.TryStmt;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.PrimitiveType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.visitor.ModifierVisitor;
import com.github.javaparser.ast.visitor.Visitable;
import com.github.javaparser.resolution.types.ResolvedType;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;

public class TryCatchAdder extends ModifierVisitor<Void> {

    public static void main(String[] args) throws IOException {
        if (args.length < 1) {
            System.out.println("Please provide the path to the Java file.");
            return;
        }
        FileReader inputFile = new FileReader(args[0]);
        String out;
        try{
            CompilationUnit cu = StaticJavaParser.parse(inputFile);
            cu.accept(new TryCatchAdder(), null);
            out = cu.toString();
        } catch (Exception e) {
            out = "";
        }

        FileWriter outFile = new FileWriter(args[1]);
        outFile.write(out);
        outFile.close();
    }

    @Override
    public Visitable visit(MethodDeclaration method, Void arg) {
        super.visit(method, arg);

        if (method.getBody().isPresent()) {
            BlockStmt body = method.getBody().get();

            // Create try block with the original method body
            TryStmt tryCatch = new TryStmt();
            tryCatch.setTryBlock(body.clone());

            // Create catch block based on method return type
            BlockStmt catchBlock = new BlockStmt();

            // Get declared exceptions if any

            if (!method.getType().isVoidType()) {
                catchBlock.addStatement(
                    new ReturnStmt(getDefaultValueForType(method.getType())));

            } else {
                catchBlock.addStatement(new ReturnStmt());
            }
            tryCatch.setCatchClauses(NodeList.nodeList(new CatchClause(
                StaticJavaParser.parseParameter("Exception e"), catchBlock)));

            body.setStatements(NodeList.nodeList(tryCatch));
        }
        return method;
    }
    private Expression getDefaultValueForType(Type type) {
        if (type.isPrimitiveType()) {
            PrimitiveType primitiveType = type.asPrimitiveType();
            switch (primitiveType.getType()) {
            case BOOLEAN:
                return new BooleanLiteralExpr(false);
            case CHAR:
                return new CharLiteralExpr('\0');
            case BYTE:
            case SHORT:
            case INT:
            case LONG:
                return StaticJavaParser.parseExpression("0");
            case FLOAT:
                return StaticJavaParser.parseExpression("0.0f");
            case DOUBLE:
                return StaticJavaParser.parseExpression("0.0");
            default:
                return new NullLiteralExpr();
            }
        } else if (type.isArrayType()) {
            return new NullLiteralExpr();
        } else if (type.isClassOrInterfaceType()) {
            ClassOrInterfaceType classType = type.asClassOrInterfaceType();

            switch (classType.getNameAsString()) {
            case "Boolean":
                return new BooleanLiteralExpr(false);
            case "Character":
                return new CharLiteralExpr('\0');
            case "Byte":
            case "Short":
            case "Integer":
            case "Long":
                return StaticJavaParser.parseExpression("0");
            case "Float":
                return StaticJavaParser.parseExpression("0.0f");
            case "Double":
                return StaticJavaParser.parseExpression("0.0");
            default:
                return new NullLiteralExpr();
            }
        } else {
            // For any other types (interfaces, etc.), return null
            return new NullLiteralExpr();
        }
    }
}
